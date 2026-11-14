import datetime
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import politica_reembolsos_sandbox as policy
from app.models.amortizacion import CuotaAmortizacion
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.pago import Pago
from app.models.solicitud_reembolso import SolicitudReembolsoSandbox
from app.models.usuario import Usuario
from app.models.wompi_pago import WompiPago
from test_wompi_postgres_concurrency import isolated_engine


@pytest.mark.skipif(not os.getenv("POSTGRES_TEST_DATABASE_URL"), reason="Requiere PostgreSQL local aislado")
def test_solicitudes_concurrentes_un_registro_y_ningun_envio(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_test_ficticia")
    monkeypatch.setenv("WOMPI_SANDBOX_REFUND_POLICY_ENABLED", "true")
    engine = isolated_engine()
    Session = sessionmaker(bind=engine, autoflush=False)
    ident = uuid4().hex
    try:
        with Session() as db:
            admin = Usuario(email=f"{ident}@example.invalid", password_hash="x", rol="ADMIN", activo=True)
            db.add(admin); db.flush()
            client = Cliente(nombre="Prueba", cedula=ident[:12], telefono="3000000000", usuario_id=admin.id)
            db.add(client); db.flush()
            credit = Credito(cliente_id=client.id, monto=Decimal("1250"), plazo_meses=1, tasa_interes=Decimal("0"), estado="DESEMBOLSADO")
            db.add(credit); db.flush()
            quota = CuotaAmortizacion(credito_id=credit.id, numero_cuota=1, fecha_vencimiento=datetime.datetime(2026, 12, 1),
                monto_cuota=Decimal("1250"), capital=Decimal("1250"), interes=Decimal("0"), saldo_remanente=Decimal("0"), monto_pagado=Decimal("1250"), estado="PAGADA")
            db.add(quota); db.flush()
            attempt = WompiPago(credito_id=credit.id, cuota_id=quota.id, referencia=ident, wompi_link_id=f"link-{ident}",
                wompi_transaction_id=f"tx-{ident}", monto_esperado=Decimal("1250"), estado="PAGADO")
            db.add(attempt); db.add(Pago(credito_id=credit.id, cuota_id=quota.id, monto_pagado=Decimal("1250"), metodo_pago="WOMPI_SANDBOX"))
            db.commit(); attempt_id, admin_id, quota_id = attempt.id, admin.id, quota.id
        started, release = threading.Event(), threading.Event()
        def consultar(_):
            started.set()
            assert release.wait(10)
            return {"id": f"tx-{ident}", "payment_link_id": f"link-{ident}", "status": "APPROVED", "amount_in_cents": 125000, "currency": "COP"}
        monkeypatch.setattr(policy, "consultar_transaccion", consultar)
        data = policy.NuevaSolicitud(wompi_pago_id=attempt_id, monto_centavos=10000, motivo="PAGO_DUPLICADO",
            descripcion="Solicitud ficticia de prueba", clasificacion="PASIVO_SALDO_A_FAVOR", evidencia="Caso de prueba")
        def crear():
            with Session() as db:
                return policy.crear(data, db, db.get(Usuario, admin_id))
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(crear)
            assert started.wait(10)
            second = pool.submit(crear)
            release.set()
            results = []
            for future in (first, second):
                try:
                    results.append(future.result(timeout=10))
                except HTTPException as exc:
                    assert exc.status_code == 409
            assert len(results) == 1 and results[0]["autorizacion"] == "PENDIENTE"
        with Session() as db:
            assert db.query(SolicitudReembolsoSandbox).filter_by(wompi_pago_id=attempt_id).count() == 1
            assert db.get(CuotaAmortizacion, quota_id).monto_pagado == Decimal("1250")
            solicitud_id = results[0]["id"]
            policy.decidir(solicitud_id, policy.Decision(decision="APROBADA", justificacion="Aprobación de prueba"), db, db.get(Usuario, admin_id))
        provider_started, provider_release = threading.Event(), threading.Event()
        calls = []
        def refund(**kwargs):
            calls.append(kwargs)
            provider_started.set()
            assert provider_release.wait(10)
            return {"status": "APPROVED", "refund_id": "12345"}
        monkeypatch.setattr(policy, "solicitar_reembolso_sandbox", refund)
        def ejecutar():
            with Session() as db:
                return policy.ejecutar(solicitud_id, db, db.get(Usuario, admin_id))
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(ejecutar)
            assert provider_started.wait(10)
            with Session() as db:
                with pytest.raises(HTTPException) as active:
                    policy.recuperar(solicitud_id, db, db.get(Usuario, admin_id))
                assert active.value.status_code == 409
            second = pool.submit(ejecutar)
            try:
                with pytest.raises(HTTPException) as exc:
                    second.result(timeout=10)
                assert exc.value.status_code == 409
            finally:
                provider_release.set()
            assert first.result(timeout=10)["ejecucion"] == "CONFIRMADO"
        assert len(calls) == 1
        from app.models.wompi_reembolso import WompiReembolsoSandbox
        from app.models.audit_log import AuditLog
        with Session() as db:
            s = db.get(SolicitudReembolsoSandbox, solicitud_id)
            refund_row = db.get(WompiReembolsoSandbox, s.reembolso_id)
            s.ejecucion = refund_row.estado = "CREANDO"
            refund_row.creado_en = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
            db.commit()
        def recuperar():
            with Session() as db:
                return policy.recuperar(solicitud_id, db, db.get(Usuario, admin_id))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = []
            for future in (pool.submit(recuperar), pool.submit(recuperar)):
                try:
                    results.append(future.result(timeout=10))
                except HTTPException as exc:
                    assert exc.status_code == 409
            assert any(x["ejecucion"] == "INCIERTO" for x in results)
        with Session() as db:
            assert db.get(SolicitudReembolsoSandbox, solicitud_id).ejecucion == "INCIERTO"
            assert db.query(AuditLog).filter_by(accion="RECUPERAR_RESERVA_REEMBOLSO_SANDBOX", entidad_id=solicitud_id).count() == 1
            assert db.get(CuotaAmortizacion, quota_id).monto_pagado == Decimal("1250")
        assert len(calls) == 1
    finally:
        engine.dispose()
