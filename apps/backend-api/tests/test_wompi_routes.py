import hashlib
import os
import datetime
import json
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "wompi-route-test-secret-not-for-production")

from decimal import Decimal

from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import wompi as wompi_endpoint
from app.config.database import Base
from app.models.amortizacion import CuotaAmortizacion
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.pago import Pago
from app.models.usuario import Usuario
from app.models.wompi_pago import WompiPago
from app.models.audit_log import AuditLog
from app.models.wompi_reembolso import WompiReembolsoSandbox
from app.api.v1.endpoints import conciliacion_sandbox as cotejo


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(bind=engine)


def make_event(secret="test_events_route", status="APPROVED", transaction_id="route-tx-001", environment="test"):
    event = {
        "event": "transaction.updated",
        "data": {"transaction": {
            "id": transaction_id,
            "status": status,
            "amount_in_cents": 125000,
            "currency": "COP",
            "payment_link_id": "route-link-001",
        }},
        "environment": environment,
        "signature": {"properties": [
            "transaction.id", "transaction.status", "transaction.amount_in_cents",
        ]},
        "timestamp": 1792600000,
    }
    raw = f"{transaction_id}{status}1250001792600000" + secret
    event["signature"]["checksum"] = hashlib.sha256(raw.encode()).hexdigest()
    return event


def call_webhook(event, checksum=None, production=False, provider=None):
    body = json.dumps(event).encode()
    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.request", "body": b"", "more_body": False}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    path = "/integraciones/wompi/production/eventos" if production else "/integraciones/wompi/sandbox/eventos"
    request = Request({"type": "http", "method": "POST", "path": path, "headers": [], "query_string": b""}, receive)
    db = Session()
    try:
        handler = wompi_endpoint.recibir_evento_produccion if production else wompi_endpoint.recibir_evento_sandbox
        authoritative = provider if provider is not None else event["data"]["transaction"].copy()
        patch_args = {"side_effect": authoritative} if isinstance(authoritative, Exception) else {"return_value": authoritative}
        with patch.object(wompi_endpoint, "consultar_transaccion", **patch_args):
            return asyncio.run(handler(request, db, checksum))
    finally:
        db.close()


def test_evento_reembolso_firmado_se_registra_sin_modificar_cartera(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    event = {"event": "refund.updated", "environment": "test", "timestamp": 1794439585,
             "data": {"refund": {"id": 32935, "status": "APPROVED", "amount_in_cents": 100000,
                                  "transaction_id": "no-protegido-por-la-firma"}},
             "signature": {"properties": ["refund.id", "refund.status", "refund.amount_in_cents"]}}
    event["signature"]["checksum"] = hashlib.sha256(
        b"32935APPROVED1000001794439585test_events_route").hexdigest()
    result = call_webhook(event, provider={})
    assert result == {"recibido": True, "procesado": False, "requiere_revision": True}
    with Session() as db:
        audit = db.query(AuditLog).filter_by(accion="EVENTO_REEMBOLSO_WOMPI_SANDBOX").one()
        assert audit.entidad_id == 32935
        assert json.loads(audit.detalles) == {"estado_wompi": "APPROVED", "monto_centavos": 100000,
                                             "transaccion_verificada": False}
        assert db.query(Pago).count() == 0
        assert db.query(WompiReembolsoSandbox).count() == 0
    event["data"]["refund"]["amount_in_cents"] = 200000
    with pytest.raises(HTTPException) as exc:
        call_webhook(event, provider={})
    assert exc.value.status_code == 401


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    os.environ["ENVIRONMENT"] = "test"
    os.environ["WOMPI_ENVIRONMENT"] = "sandbox"
    os.environ["WOMPI_PRIVATE_KEY"] = "prv_test_route"
    os.environ["WOMPI_EVENTS_SECRET"] = "test_events_route"
    user = Usuario(email="client@example.test", password_hash="not-used", rol="CLIENTE", activo=True)
    db = Session()
    db.add(user)
    db.flush()
    client_record = Cliente(nombre="Sandbox Client", cedula="100000001", telefono="3000000000", usuario_id=user.id)
    db.add(client_record)
    db.flush()
    credit = Credito(cliente_id=client_record.id, monto=Decimal("1250.00"), plazo_meses=1, tasa_interes=Decimal("0"), estado="DESEMBOLSADO")
    db.add(credit)
    db.flush()
    quota = CuotaAmortizacion(
        credito_id=credit.id, numero_cuota=1, fecha_vencimiento=datetime.datetime(2026, 11, 1),
        monto_cuota=Decimal("1250.00"), capital=Decimal("1250.00"), interes=Decimal("0"),
        saldo_remanente=Decimal("0"), monto_pagado=Decimal("0"), estado="PENDIENTE",
    )
    db.add(quota)
    db.flush()
    intent = WompiPago(
        credito_id=credit.id, cuota_id=quota.id, referencia="internal-route-ref",
        wompi_link_id="route-link-001", monto_esperado=Decimal("1250.00"),
        estado="PENDIENTE", checkout_url="https://checkout.wompi.co/l/route-link-001",
    )
    db.add(intent)
    db.commit()
    db.close()


def test_webhook_aplica_pago_aprobado_y_es_idempotente():
    event = make_event()
    checksum = event["signature"]["checksum"]
    first = call_webhook(event, checksum)
    second = call_webhook(event, checksum)
    assert first["estado"] == "PAGADO"
    assert second["duplicado"] is True
    db = Session()
    try:
        assert db.query(Pago).count() == 1
        assert db.query(CuotaAmortizacion).one().estado == "PAGADA"
        assert db.query(WompiPago).one().wompi_transaction_id == "route-tx-001"
    finally:
        db.close()


def test_webhook_procesa_aprobacion_despues_de_pendiente_con_mismo_id():
    pending_event = make_event(status="PENDING", transaction_id="route-tx-pending-001")
    pending = call_webhook(pending_event, pending_event["signature"]["checksum"])
    assert pending["estado"] == "PENDIENTE"

    approved_event = make_event(status="APPROVED", transaction_id="route-tx-pending-001")
    approved = call_webhook(approved_event, approved_event["signature"]["checksum"])
    assert approved["estado"] == "PAGADO"

    db = Session()
    try:
        assert db.query(Pago).count() == 1
        assert db.query(CuotaAmortizacion).one().estado == "PAGADA"
        assert db.query(WompiPago).one().wompi_transaction_id == "route-tx-pending-001"
    finally:
        db.close()


def test_webhook_rechaza_firma_invalida_sin_aplicar_pago():
    event = make_event()
    event["signature"]["checksum"] = "0" * 64
    with pytest.raises(HTTPException) as exc:
        call_webhook(event)
    assert exc.value.status_code == 401
    db = Session()
    try:
        assert db.query(Pago).count() == 0
        assert db.query(CuotaAmortizacion).one().monto_pagado == Decimal("0.00")
    finally:
        db.close()


def test_webhook_declinado_registra_intento_fallido_sin_aplicar_pago():
    event = make_event(status="DECLINED")
    checksum = event["signature"]["checksum"]
    first = call_webhook(event, checksum)
    second = call_webhook(event, checksum)
    assert first["estado"] == "FALLIDO"
    assert second["duplicado"] is True
    db = Session()
    try:
        intent = db.query(WompiPago).one()
        assert intent.estado == "FALLIDO"
        assert intent.wompi_transaction_id == "route-tx-001"
        assert db.query(Pago).count() == 0
        quota = db.query(CuotaAmortizacion).one()
        assert quota.estado == "PENDIENTE"
        assert quota.monto_pagado == Decimal("0.00")
    finally:
        db.close()


def test_estado_de_intento_no_expone_checkout_y_respeta_propiedad():
    db = Session()
    try:
        credit = db.query(Credito).one()
        quota = db.query(CuotaAmortizacion).one()
        user = db.query(Usuario).one()
        result = wompi_endpoint.obtener_estado_intento_cuota(credit.id, quota.id, db, user)
    finally:
        db.close()
    assert result["estado_cuota"] == "PENDIENTE"
    assert result["estado_ultimo_intento"] == "PENDIENTE"
    assert "checkout_url" not in result


def test_webhook_produccion_aplica_pago_solo_en_runtime_y_ambiente_produccion():
    os.environ["ENVIRONMENT"] = "production"
    os.environ["WOMPI_ENVIRONMENT"] = "production"
    os.environ["WOMPI_PRIVATE_KEY"] = "prv_prod_route"
    os.environ["WOMPI_EVENTS_SECRET"] = "prod_events_route"
    os.environ["WOMPI_PRODUCTION_ENABLED"] = "true"
    event = make_event(
        secret="prod_events_route",
        transaction_id="route-tx-prod-001",
        environment="prod",
    )
    result = call_webhook(event, event["signature"]["checksum"], production=True)
    assert result["estado"] == "PAGADO"
    db = Session()
    try:
        payment = db.query(Pago).one()
        assert payment.metodo_pago == "WOMPI"
        assert db.query(CuotaAmortizacion).one().estado == "PAGADA"
    finally:
        db.close()


def test_webhook_produccion_no_acepta_ruta_en_configuracion_sandbox():
    event = make_event(
        secret="prod_events_route",
        transaction_id="route-tx-prod-002",
        environment="prod",
    )
    with pytest.raises(HTTPException) as exc:
        call_webhook(event, event["signature"]["checksum"], production=True)
    assert exc.value.status_code == 404
    db = Session()
    try:
        assert db.query(Pago).count() == 0
        assert db.query(CuotaAmortizacion).one().monto_pagado == Decimal("0.00")
    finally:
        db.close()


def test_crear_link_reutiliza_intento_pendiente(monkeypatch):
    monkeypatch.setattr(wompi_endpoint, "crear_link_pago", lambda **_kwargs: pytest.fail("no debe generar un link duplicado"))
    db = Session()
    try:
        credit = db.query(Credito).one()
        quota = db.query(CuotaAmortizacion).one()
        user = db.query(Usuario).one()
        result = wompi_endpoint.crear_link_para_cuota(credit.id, quota.id, db, user)
    finally:
        db.close()
    assert result["checkout_url"].endswith("route-link-001")


def test_webhook_no_confia_en_link_ni_moneda_del_evento():
    event = make_event()
    provider = event["data"]["transaction"].copy()
    provider["payment_link_id"] = "otro-link"
    result = call_webhook(event, event["signature"]["checksum"], provider=provider)
    assert result["procesado"] is False
    db = Session()
    try:
        assert db.query(Pago).count() == 0
    finally:
        db.close()


def test_webhook_rechaza_moneda_distinta_confirmada_por_wompi():
    event = make_event()
    provider = event["data"]["transaction"].copy()
    provider["currency"] = "USD"
    with pytest.raises(HTTPException) as exc:
        call_webhook(event, event["signature"]["checksum"], provider=provider)
    assert exc.value.status_code == 400


def test_falla_consulta_wompi_no_aplica_pago():
    event = make_event()
    with pytest.raises(HTTPException) as exc:
        call_webhook(event, event["signature"]["checksum"], provider=HTTPException(status_code=502, detail="No disponible"))
    assert exc.value.status_code == 502
    db = Session()
    try:
        assert db.query(Pago).count() == 0
        assert db.query(CuotaAmortizacion).one().estado == "PENDIENTE"
    finally:
        db.close()


def test_reconciliacion_sandbox_aplica_una_vez_y_audita(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    provider = make_event()["data"]["transaction"]
    monkeypatch.setattr(wompi_endpoint, "consultar_transaccion", lambda _id: provider)
    db = Session()
    try:
        admin = Usuario(email="admin@example.invalid", password_hash="x", rol="ADMIN", activo=True)
        db.add(admin)
        db.commit()
        credit, quota = db.query(Credito).one(), db.query(CuotaAmortizacion).one()
        data = wompi_endpoint.ReconciliacionSandbox(transaction_id="route-tx-001")
        first = wompi_endpoint.reconciliar_cuota_sandbox(credit.id, quota.id, data, db, admin)
        second = wompi_endpoint.reconciliar_cuota_sandbox(credit.id, quota.id, data, db, admin)
        assert first["estado"] == "PAGADO"
        assert second["duplicado"] is True
        assert db.query(Pago).count() == 1
        assert db.query(AuditLog).filter_by(accion="RECONCILIAR_CUOTA_WOMPI_SANDBOX").count() == 1
    finally:
        db.close()


def test_reconciliacion_rechaza_link_ajeno_y_monto_incorrecto(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    provider = make_event()["data"]["transaction"]
    monkeypatch.setattr(wompi_endpoint, "consultar_transaccion", lambda _id: provider)
    db = Session()
    try:
        admin = Usuario(email="admin@example.invalid", password_hash="x", rol="ADMIN", activo=True)
        db.add(admin)
        db.commit()
        credit, quota = db.query(Credito).one(), db.query(CuotaAmortizacion).one()
        data = wompi_endpoint.ReconciliacionSandbox(transaction_id="route-tx-001")
        provider["payment_link_id"] = "otro-link"
        with pytest.raises(HTTPException) as wrong_link:
            wompi_endpoint.reconciliar_cuota_sandbox(credit.id, quota.id, data, db, admin)
        assert wrong_link.value.status_code == 409
        provider["payment_link_id"] = "route-link-001"
        provider["amount_in_cents"] = 123
        with pytest.raises(HTTPException) as wrong_amount:
            wompi_endpoint.reconciliar_cuota_sandbox(credit.id, quota.id, data, db, admin)
        assert wrong_amount.value.status_code == 409
        assert db.query(Pago).count() == 0
        assert quota.estado == "PENDIENTE"
    finally:
        db.close()


def test_revision_lista_reservas_sin_link_y_bloquea_produccion(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    db = Session()
    try:
        attempt = db.query(WompiPago).one()
        attempt.estado, attempt.checkout_url, attempt.wompi_link_id = "INCIERTO", None, None
        db.commit()
        result = wompi_endpoint.listar_enlaces_por_revisar(db, db.query(Usuario).one())
        assert len(result["intentos"]) == 1
        assert result["intentos"][0]["estado"] == "INCIERTO"
        assert "checkout_url" not in result["intentos"][0]
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(HTTPException) as exc:
            wompi_endpoint.listar_enlaces_por_revisar(db, db.query(Usuario).one())
        assert exc.value.status_code == 404
    finally:
        db.close()


def test_reconciliacion_requiere_admin(client, monkeypatch):
    from app.core.deps import get_current_active_user
    from main import app
    from types import SimpleNamespace
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    monkeypatch.setattr(wompi_endpoint, "consultar_transaccion", lambda _id: pytest.fail("no debe consultar Wompi"))
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=42, rol="CLIENTE", activo=True)
    response = client.post("/integraciones/wompi/sandbox/creditos/1/cuotas/1/reconciliar", json={"transaction_id": "route-tx-001"})
    assert response.status_code == 403
    assert client.get("/integraciones/wompi/sandbox/revision-enlaces").status_code == 403


def test_pago_ya_aplicado_con_estado_cambiado_genera_alerta_sin_alterar_saldo():
    approved = make_event()
    assert call_webhook(approved, approved["signature"]["checksum"])["estado"] == "PAGADO"
    voided = make_event(status="VOIDED")
    assert call_webhook(voided, voided["signature"]["checksum"])["requiere_revision"] is True
    assert call_webhook(voided, voided["signature"]["checksum"])["requiere_revision"] is True
    db = Session()
    try:
        quota = db.query(CuotaAmortizacion).one()
        assert quota.estado == "PAGADA" and quota.monto_pagado == Decimal("1250.00")
        assert db.query(Pago).count() == 1
        assert db.query(AuditLog).filter_by(accion="ALERTA_CAMBIO_ESTADO_WOMPI", resultado="REQUIERE_REVISION").count() == 1
    finally:
        db.close()


def test_comparacion_sandbox_muestra_coincidencias_y_alerta_cambio(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    approved = make_event()
    call_webhook(approved, approved["signature"]["checksum"])
    provider = approved["data"]["transaction"].copy()
    monkeypatch.setattr(wompi_endpoint, "consultar_transaccion", lambda _id: provider)
    db = Session()
    try:
        quota = db.query(CuotaAmortizacion).one()
        ok = wompi_endpoint.comparar_cuota_sandbox(quota.credito_id, quota.id, db, db.query(Usuario).one())
        assert ok["resultado"] == "COINCIDE_RECAUDO_NO_CONCILIACION_BANCARIA"
        assert ok["abono_bancario_verificado"] is False and ok["reembolsos_verificados"] is False
        provider["status"] = "VOIDED"
        changed = wompi_endpoint.comparar_cuota_sandbox(quota.credito_id, quota.id, db, db.query(Usuario).one())
        assert changed["resultado"] == "REQUIERE_REVISION"
        assert "ESTADO_NO_CONFIRMADO_O_CAMBIO_DE_ESTADO" in changed["motivos"]
        provider["status"] = "APPROVED"
        provider["amount_in_cents"] = 125001
        assert "MONTO_O_MONEDA_NO_COINCIDE" in wompi_endpoint.comparar_cuota_sandbox(quota.credito_id, quota.id, db, db.query(Usuario).one())["motivos"]
        provider["amount_in_cents"] = 125000
        quota.estado = "PENDIENTE"
        assert "SALDO_CUOTA_NO_COINCIDE_CON_PAGOS_WOMPI" in wompi_endpoint.comparar_cuota_sandbox(quota.credito_id, quota.id, db, db.query(Usuario).one())["motivos"]
        assert db.query(Pago).count() == 1 and quota.monto_pagado == Decimal("1250.00")
    finally:
        db.close()


def test_comparacion_no_inventa_transaccion_y_requiere_admin(client, monkeypatch):
    from app.core.deps import get_current_active_user
    from main import app
    from types import SimpleNamespace
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    monkeypatch.setattr(wompi_endpoint, "consultar_transaccion", lambda _id: pytest.fail("no hay ID para consultar"))
    db = Session()
    try:
        quota = db.query(CuotaAmortizacion).one()
        result = wompi_endpoint.comparar_cuota_sandbox(quota.credito_id, quota.id, db, db.query(Usuario).one())
        assert result["resultado"] == "REQUIERE_REVISION"
        assert result["motivos"] == ["SIN_TRANSACCION_REGISTRADA_EN_CREDIFRESH"]
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(HTTPException) as exc:
            wompi_endpoint.comparar_cuota_sandbox(quota.credito_id, quota.id, db, db.query(Usuario).one())
        assert exc.value.status_code == 404
    finally:
        db.close()
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=42, rol="CLIENTE", activo=True)
    assert client.get("/integraciones/wompi/sandbox/creditos/1/cuotas/1/comparar").status_code == 403


def test_reembolso_sandbox_reserva_una_vez_y_no_modifica_cartera(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    event = make_event()
    call_webhook(event, event["signature"]["checksum"])
    provider = event["data"]["transaction"]
    monkeypatch.setattr(wompi_endpoint, "consultar_transaccion", lambda _id: provider)
    calls = []
    def refund(**kwargs):
        calls.append(kwargs)
        return {"status": "APPROVED", "refund_id": "refund-test-1"}
    monkeypatch.setattr(wompi_endpoint, "solicitar_reembolso_sandbox", refund)
    db = Session()
    try:
        admin = Usuario(email="refund-admin@example.invalid", password_hash="x", rol="ADMIN", activo=True)
        db.add(admin)
        db.commit()
        quota = db.query(CuotaAmortizacion).one()
        data = wompi_endpoint.ReembolsoSandboxInput(monto_centavos=25000, escenario="approved")
        result = wompi_endpoint.crear_reembolso_de_prueba(quota.credito_id, quota.id, data, db, admin)
        again = wompi_endpoint.crear_reembolso_de_prueba(quota.credito_id, quota.id, data, db, admin)
        assert result["estado"] == "CONFIRMADO" and result["saldo_cartera_modificado"] is False
        assert again["ya_existia"] is True and len(calls) == 1
        assert db.query(WompiReembolsoSandbox).count() == 1 and db.query(Pago).count() == 1
        assert quota.estado == "PAGADA" and quota.monto_pagado == Decimal("1250.00")
        assert wompi_endpoint.consultar_reembolso_de_prueba(quota.credito_id, quota.id, db, admin)["estado"] == "CONFIRMADO"
        assert "REEMBOLSO_DE_PRUEBA_REQUIERE_REVISION" in wompi_endpoint.comparar_cuota_sandbox(quota.credito_id, quota.id, db, admin)["motivos"]
        with pytest.raises(HTTPException) as exc:
            wompi_endpoint.crear_reembolso_de_prueba(quota.credito_id, quota.id,
                wompi_endpoint.ReembolsoSandboxInput(monto_centavos=30000, escenario="approved"), db, admin)
        assert exc.value.status_code == 409 and len(calls) == 1
    finally:
        db.close()


def test_reembolso_incierto_no_se_reenvia(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    event = make_event()
    call_webhook(event, event["signature"]["checksum"])
    monkeypatch.setattr(wompi_endpoint, "consultar_transaccion", lambda _id: event["data"]["transaction"])
    calls = []
    def timeout(**kwargs):
        calls.append(1)
        raise TimeoutError()
    monkeypatch.setattr(wompi_endpoint, "solicitar_reembolso_sandbox", timeout)
    db = Session()
    try:
        admin = Usuario(email="uncertain@example.invalid", password_hash="x", rol="ADMIN", activo=True)
        db.add(admin)
        db.commit()
        quota = db.query(CuotaAmortizacion).one()
        data = wompi_endpoint.ReembolsoSandboxInput(monto_centavos=125000, escenario="approved")
        assert wompi_endpoint.crear_reembolso_de_prueba(quota.credito_id, quota.id, data, db, admin)["estado"] == "INCIERTO"
        assert wompi_endpoint.crear_reembolso_de_prueba(quota.credito_id, quota.id, data, db, admin)["ya_existia"]
        assert len(calls) == 1 and quota.monto_pagado == Decimal("1250.00")
        monkeypatch.setattr(wompi_endpoint, "consultar_reembolso_sandbox", lambda _id: {
            "respuesta_http_wompi": 200, "datos_confirmados": True, "estado": "APPROVED",
            "monto_centavos": 125000, "transaction_id": "route-tx-001"})
        check = wompi_endpoint.comprobar_reembolso_proveedor_sandbox(quota.credito_id, quota.id, "32935", db, admin)
        assert check["transaccion_coincide"] and check["monto_coincide"]
        assert check["estado_local"] == "INCIERTO" and check["requiere_revision"] and not check["cartera_modificada"]
        assert db.query(Pago).count() == 1 and len(calls) == 1
    finally:
        db.close()


def test_reembolso_rechazado_y_monto_excesivo_no_alteran_cartera(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    event = make_event()
    call_webhook(event, event["signature"]["checksum"])
    monkeypatch.setattr(wompi_endpoint, "consultar_transaccion", lambda _id: event["data"]["transaction"])
    calls = []
    def rejected(**kwargs):
        calls.append(1)
        return {"status": "DECLINED", "refund_id": "refund-declined"}
    monkeypatch.setattr(wompi_endpoint, "solicitar_reembolso_sandbox", rejected)
    db = Session()
    try:
        admin = Usuario(email="declined@example.invalid", password_hash="x", rol="ADMIN", activo=True)
        db.add(admin)
        db.commit()
        quota = db.query(CuotaAmortizacion).one()
        with pytest.raises(HTTPException) as exc:
            wompi_endpoint.crear_reembolso_de_prueba(quota.credito_id, quota.id,
                wompi_endpoint.ReembolsoSandboxInput(monto_centavos=125001, escenario="approved"), db, admin)
        assert exc.value.status_code == 409 and calls == []
        result = wompi_endpoint.crear_reembolso_de_prueba(quota.credito_id, quota.id,
            wompi_endpoint.ReembolsoSandboxInput(monto_centavos=125000, escenario="declined"), db, admin)
        assert result["estado"] == "NO_APROBADO" and result["estado_wompi"] == "DECLINED"
        assert quota.estado == "PAGADA" and quota.monto_pagado == Decimal("1250.00") and len(calls) == 1
    finally:
        db.close()


def test_caida_al_guardar_respuesta_conserva_reserva_y_no_reenvia(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    event = make_event()
    call_webhook(event, event["signature"]["checksum"])
    monkeypatch.setattr(wompi_endpoint, "consultar_transaccion", lambda _id: event["data"]["transaction"])
    calls = []
    monkeypatch.setattr(wompi_endpoint, "solicitar_reembolso_sandbox", lambda **_kwargs:
        (calls.append(1) or {"status": "APPROVED", "refund_id": "refund-ficticio"}))
    db = Session()
    try:
        admin = Usuario(email="crash@example.invalid", password_hash="x", rol="ADMIN", activo=True)
        db.add(admin)
        db.commit()
        quota = db.query(CuotaAmortizacion).one()
        credit_id, quota_id, admin_id = quota.credito_id, quota.id, admin.id
        real_commit = db.commit
        count = []
        def fail_second_commit():
            count.append(1)
            if len(count) == 2:
                raise RuntimeError("fallo simulado al guardar")
            real_commit()
        monkeypatch.setattr(db, "commit", fail_second_commit)
        data = wompi_endpoint.ReembolsoSandboxInput(monto_centavos=10000, escenario="approved")
        with pytest.raises(RuntimeError):
            wompi_endpoint.crear_reembolso_de_prueba(credit_id, quota_id, data, db, admin)
        db.rollback()
        with Session() as check:
            stored = check.query(WompiReembolsoSandbox).one()
            assert stored.estado == "CREANDO"
            result = wompi_endpoint.crear_reembolso_de_prueba(credit_id, quota_id, data, check, check.get(Usuario, admin_id))
            assert result["ya_existia"] is True and result["estado"] == "CREANDO"
            assert check.query(Pago).count() == 1
        assert len(calls) == 1
    finally:
        db.close()


def test_reembolso_exige_admin_ambiente_y_monto_valido(client, monkeypatch):
    from app.core.deps import get_current_active_user
    from main import app
    from types import SimpleNamespace
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(HTTPException) as exc:
        wompi_endpoint._exigir_sandbox_recaudo()
    assert exc.value.status_code == 404
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=42, rol="CLIENTE", activo=True)
    response = client.post("/integraciones/wompi/sandbox/creditos/1/cuotas/1/reembolso", json={"monto_centavos": 1, "escenario": "approved"})
    assert response.status_code == 403
    response = client.get("/integraciones/wompi/sandbox/creditos/1/cuotas/1/reembolso/consulta-proveedor?refund_id=32935")
    assert response.status_code == 403
    with pytest.raises(ValueError):
        wompi_endpoint.ReembolsoSandboxInput(monto_centavos=1.1, escenario="approved")


def test_cotejo_informe_sandbox_no_declara_banco_verificado(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    event = make_event()
    call_webhook(event, event["signature"]["checksum"])
    monkeypatch.setattr(cotejo, "consultar_transaccion", lambda _id: event["data"]["transaction"])
    payload = {"periodo_desde": "2026-11-01", "periodo_hasta": "2026-11-10", "referencia_abono_wompi": "SBX-ABONO-1",
        "transacciones": [{"transaction_id": "route-tx-001", "monto_centavos": 125000}],
        "comisiones_centavos": 2000, "impuestos_centavos": 380, "reembolsos_centavos": 0,
        "otros_descuentos_centavos": 0, "neto_informe_centavos": 122620,
        "referencia_abono_banco": "SBX-ABONO-1", "abono_banco_centavos": 122620}
    db = Session()
    try:
        admin = Usuario(email="reconcile@example.invalid", password_hash="x", rol="ADMIN", activo=True)
        db.add(admin)
        db.commit()
        result = cotejo.comparar_informe_sandbox(cotejo.InformeSandbox(**payload), db, admin)
        assert result["cotejo_sin_diferencias"] is True and result["resultado"] == "REQUIERE_REVISION"
        assert result["informes_autenticados_o_completitud_verificada"] is False
        assert result["neto_calculado_centavos"] == 122620
        assert db.query(AuditLog).filter_by(accion="COTEJAR_INFORME_WOMPI_SANDBOX").count() == 1
        quota = db.query(CuotaAmortizacion).one()
        quota.estado = "PENDIENTE"
        db.flush()
        mismatch = cotejo.comparar_informe_sandbox(cotejo.InformeSandbox(**payload), db, admin)
        assert "DIFERENCIA_TRANSACCION_O_CARTERA" in {x["motivo"] for x in mismatch["diferencias"]}
        quota.estado = "PAGADA"
        db.flush()
        payload["abono_banco_centavos"] = 122621
        payload["referencia_abono_banco"] = "OTRO-ABONO"
        different = cotejo.comparar_informe_sandbox(cotejo.InformeSandbox(**payload), db, admin)
        assert {x["motivo"] for x in different["diferencias"]} == {"MONTO_ABONO_NO_COINCIDE", "REFERENCIAS_ABONO_NO_COINCIDEN"}
        payload["transacciones"][0]["transaction_id"] = "no-existe"
        missing = cotejo.comparar_informe_sandbox(cotejo.InformeSandbox(**payload), db, admin)
        assert "NO_REGISTRADA_EN_CARTERA" in {x["motivo"] for x in missing["diferencias"]}
        payload["transacciones"] *= 2
        with pytest.raises(ValueError):
            cotejo.InformeSandbox(**payload)
        assert db.query(Pago).count() == 1
    finally:
        db.close()


def test_cotejo_informe_restringido_a_admin_y_sandbox(client, monkeypatch):
    from app.core.deps import get_current_active_user
    from main import app
    from types import SimpleNamespace
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=42, rol="CLIENTE", activo=True)
    body = {"periodo_desde":"2026-11-01", "periodo_hasta":"2026-11-10", "referencia_abono_wompi":"A",
        "transacciones":[{"transaction_id":"tx-test", "monto_centavos":100}], "comisiones_centavos":0,
        "impuestos_centavos":0, "reembolsos_centavos":0, "otros_descuentos_centavos":0,
        "neto_informe_centavos":100, "referencia_abono_banco":"A", "abono_banco_centavos":100}
    assert client.post("/integraciones/wompi/sandbox/conciliacion-informe", json=body).status_code == 403
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(HTTPException) as exc:
        cotejo.comparar_informe_sandbox(cotejo.InformeSandbox(**body), None, None)
    assert exc.value.status_code == 404


def test_creacion_incierta_no_se_repite(monkeypatch):
    db = Session()
    try:
        db.query(WompiPago).delete()
        db.commit()
        credit, quota, user = db.query(Credito).one(), db.query(CuotaAmortizacion).one(), db.query(Usuario).one()
        calls = []
        def unavailable(**_kwargs):
            calls.append(1)
            raise TimeoutError()
        monkeypatch.setattr(wompi_endpoint, "crear_link_pago", unavailable)
        with pytest.raises(HTTPException) as first:
            wompi_endpoint.crear_link_para_cuota(credit.id, quota.id, db, user)
        assert first.value.status_code == 503
        with pytest.raises(HTTPException) as second:
            wompi_endpoint.crear_link_para_cuota(credit.id, quota.id, db, user)
        assert second.value.status_code == 409
        assert len(calls) == 1
        assert db.query(WompiPago).one().estado == "INCIERTO"
    finally:
        db.close()


def test_falta_de_configuracion_no_deja_reserva_incierta(monkeypatch):
    db = Session()
    try:
        db.query(WompiPago).delete()
        db.commit()
        monkeypatch.delenv("WOMPI_PRIVATE_KEY", raising=False)
        with pytest.raises(HTTPException) as exc:
            wompi_endpoint.crear_link_para_cuota(db.query(Credito).one().id, db.query(CuotaAmortizacion).one().id, db, db.query(Usuario).one())
        assert exc.value.status_code == 503
        assert db.query(WompiPago).count() == 0
    finally:
        db.close()


def test_link_fallido_se_reutiliza_para_evitar_dos_links(monkeypatch):
    db = Session()
    try:
        db.query(WompiPago).one().estado = "FALLIDO"
        db.commit()
        monkeypatch.setattr(wompi_endpoint, "crear_link_pago", lambda **_kwargs: pytest.fail("no generar otro link"))
        result = wompi_endpoint.crear_link_para_cuota(db.query(Credito).one().id, db.query(CuotaAmortizacion).one().id, db, db.query(Usuario).one())
        assert result["estado"] == "FALLIDO"
    finally:
        db.close()


def test_base_impide_dos_reservas_abiertas_para_la_misma_cuota():
    db = Session()
    try:
        original = db.query(WompiPago).one()
        db.add(WompiPago(credito_id=original.credito_id, cuota_id=original.cuota_id,
                         referencia="otra-referencia", monto_esperado=original.monto_esperado,
                         estado="CREANDO"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.query(WompiPago).count() == 1
    finally:
        db.close()


def test_no_reutiliza_link_si_el_saldo_cambio(monkeypatch):
    db = Session()
    try:
        quota = db.query(CuotaAmortizacion).one()
        quota.monto_pagado = Decimal("1.00")
        db.commit()
        monkeypatch.setattr(wompi_endpoint, "crear_link_pago", lambda **_kwargs: pytest.fail("no generar otro link"))
        with pytest.raises(HTTPException) as exc:
            wompi_endpoint.crear_link_para_cuota(db.query(Credito).one().id, quota.id, db, db.query(Usuario).one())
        assert exc.value.status_code == 409
        assert "saldo cambió" in exc.value.detail
    finally:
        db.close()


def test_evento_sin_id_firmado_no_puede_iniciar_consulta():
    event = make_event()
    event["signature"]["properties"] = ["transaction.status", "transaction.amount_in_cents"]
    event["signature"]["checksum"] = hashlib.sha256(b"APPROVED1250001792600000test_events_route").hexdigest()
    with pytest.raises(HTTPException) as exc:
        call_webhook(event, event["signature"]["checksum"])
    assert exc.value.status_code == 401


def test_dos_peticiones_simultaneas_no_crean_dos_links(tmp_path, monkeypatch):
    local_engine = create_engine(f"sqlite:///{(tmp_path / 'pagos.sqlite').as_posix()}",
                                 connect_args={"check_same_thread": False})
    Base.metadata.create_all(local_engine)
    LocalSession = sessionmaker(bind=local_engine, autoflush=False, autocommit=False)
    db = LocalSession()
    try:
        user = Usuario(email="cliente@prueba.invalid", password_hash="x", rol="CLIENTE", activo=True)
        db.add(user)
        db.flush()
        person = Cliente(nombre="Cliente prueba", cedula="123456789", telefono="3000000000", usuario_id=user.id)
        db.add(person)
        db.flush()
        credit = Credito(cliente_id=person.id, monto=Decimal("1250.00"), plazo_meses=1,
                         tasa_interes=Decimal("0"), estado="DESEMBOLSADO")
        db.add(credit)
        db.flush()
        quota = CuotaAmortizacion(credito_id=credit.id, numero_cuota=1,
            fecha_vencimiento=datetime.datetime(2026, 12, 1), monto_cuota=Decimal("1250.00"),
            capital=Decimal("1250.00"), interes=Decimal("0"), saldo_remanente=Decimal("0"),
            monto_pagado=Decimal("0"), estado="PENDIENTE")
        db.add(quota)
        db.commit()
        credit_id, quota_id, user_id = credit.id, quota.id, user.id
    finally:
        db.close()

    started, finish = threading.Event(), threading.Event()
    calls = []
    def create_fake_link(**_kwargs):
        calls.append(1)
        started.set()
        assert finish.wait(5)
        return {"id": "link-unico", "checkout_url": "https://checkout.wompi.co/l/link-unico", "ambiente": "sandbox"}
    monkeypatch.setattr(wompi_endpoint, "crear_link_pago", create_fake_link)

    def request_link():
        session = LocalSession()
        try:
            return wompi_endpoint.crear_link_para_cuota(credit_id, quota_id, session, session.get(Usuario, user_id))
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request_link)
            assert started.wait(5)
            second = pool.submit(request_link)
            try:
                with pytest.raises(HTTPException) as exc:
                    second.result(timeout=5)
                assert exc.value.status_code == 409
            finally:
                finish.set()
            assert first.result(timeout=5)["checkout_url"].endswith("link-unico")
        assert len(calls) == 1
    finally:
        local_engine.dispose()
