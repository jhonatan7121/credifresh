"""Terminación de un proceso trabajador con PostgreSQL local y proveedor simulado."""
import datetime
import os
import subprocess
import sys
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import politica_reembolsos_sandbox as policy
from app.models.amortizacion import CuotaAmortizacion
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.pago import Pago
from app.models.solicitud_reembolso import SolicitudReembolsoSandbox
from app.models.usuario import Usuario
from app.models.wompi_pago import WompiPago
from app.models.wompi_reembolso import WompiReembolsoSandbox
from test_wompi_postgres_concurrency import isolated_engine


@pytest.mark.skipif(not os.getenv("POSTGRES_TEST_DATABASE_URL"), reason="Requiere PostgreSQL local aislado")
@pytest.mark.parametrize("fase", ["antes_envio", "durante_envio", "despues_procesar"])
def test_terminacion_real_preserva_reserva(monkeypatch, tmp_path, fase):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_test_ficticia")
    monkeypatch.setenv("WOMPI_SANDBOX_REFUND_POLICY_ENABLED", "true")
    engine = isolated_engine()
    Sessions = sessionmaker(bind=engine, autoflush=False)
    ident = uuid4().hex
    tx = {"id": f"tx-{ident}", "payment_link_id": f"link-{ident}", "status": "APPROVED", "amount_in_cents": 125000, "currency": "COP"}
    monkeypatch.setattr(policy, "consultar_transaccion", lambda _: tx)
    try:
        with Sessions() as db:
            admin = Usuario(email=f"{ident}@example.invalid", password_hash="x", rol="ADMIN", activo=True)
            db.add(admin); db.flush()
            cliente = Cliente(nombre="Prueba", cedula=ident[:12], telefono="3000000000", usuario_id=admin.id)
            db.add(cliente); db.flush()
            credito = Credito(cliente_id=cliente.id, monto=Decimal("1250"), plazo_meses=1, tasa_interes=Decimal("0"), estado="DESEMBOLSADO")
            db.add(credito); db.flush()
            cuota = CuotaAmortizacion(credito_id=credito.id, numero_cuota=1, fecha_vencimiento=datetime.datetime(2026, 12, 1), monto_cuota=Decimal("1250"), capital=Decimal("1250"), interes=Decimal("0"), saldo_remanente=Decimal("0"), monto_pagado=Decimal("1250"), estado="PAGADA")
            db.add(cuota); db.flush()
            intento = WompiPago(credito_id=credito.id, cuota_id=cuota.id, referencia=ident, wompi_link_id=tx["payment_link_id"], wompi_transaction_id=tx["id"], monto_esperado=Decimal("1250"), estado="PAGADO")
            db.add(intento); db.add(Pago(credito_id=credito.id, cuota_id=cuota.id, monto_pagado=Decimal("1250"), metodo_pago="WOMPI_SANDBOX")); db.commit()
            data = policy.NuevaSolicitud(wompi_pago_id=intento.id, monto_centavos=10000, motivo="PAGO_DUPLICADO", descripcion="Solicitud ficticia de prueba", clasificacion="PASIVO_SALDO_A_FAVOR", evidencia="Soporte ficticio")
            result = policy.crear(data, db, admin)
            policy.decidir(result["id"], policy.Decision(decision="APROBADA", justificacion="Aprobación sintética"), db, admin)
            sid, aid, qid = result["id"], admin.id, cuota.id
        marker = tmp_path / f"{fase}.txt"
        script = '''import os, sys\nimport main\nfrom sqlalchemy import create_engine\nfrom sqlalchemy.orm import sessionmaker\nfrom app.api.v1.endpoints import politica_reembolsos_sandbox as p\nfrom app.models.usuario import Usuario\nengine=create_engine(os.environ["POSTGRES_TEST_DATABASE_URL"])\nSession=sessionmaker(bind=engine, autoflush=False)\nphase, marker, sid, aid=sys.argv[1],sys.argv[2],int(sys.argv[3]),int(sys.argv[4])\ndef consult(tx):\n if phase == "antes_envio": os._exit(71)\n return {"id":tx,"payment_link_id":os.environ["FAKE_LINK"],"status":"APPROVED","currency":"COP","amount_in_cents":125000}\ndef refund(**kwargs):\n with open(marker,"a",encoding="utf8") as f: f.write("envio\\n"); f.flush(); os.fsync(f.fileno())\n os._exit(72 if phase == "durante_envio" else 73)\np.consultar_transaccion=consult\np.solicitar_reembolso_sandbox=refund\nwith Session() as db: p.ejecutar(sid,db,db.get(Usuario,aid))\n'''
        env = os.environ.copy(); env["FAKE_LINK"] = tx["payment_link_id"]
        proc = subprocess.run([sys.executable, "-c", script, fase, str(marker), str(sid), str(aid)], env=env, timeout=30)
        assert proc.returncode == {"antes_envio": 71, "durante_envio": 72, "despues_procesar": 73}[fase]
        with Sessions() as db:
            row = db.get(SolicitudReembolsoSandbox, sid)
            refund = db.get(WompiReembolsoSandbox, row.reembolso_id)
            assert row.ejecucion == refund.estado == "CREANDO"
            refund.creado_en = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
            db.commit()
            assert policy.recuperar(sid, db, db.get(Usuario, aid))["ejecucion"] == "INCIERTO"
            with pytest.raises(Exception):
                policy.ejecutar(sid, db, db.get(Usuario, aid))
            assert db.get(CuotaAmortizacion, qid).monto_pagado == Decimal("1250")
        assert (marker.read_text().count("envio") if marker.exists() else 0) == (0 if fase == "antes_envio" else 1)
    finally:
        engine.dispose()
