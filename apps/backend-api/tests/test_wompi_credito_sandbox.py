import asyncio
import hashlib
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from conftest import TestSessionLocal
from app.models.aceptacion_credito import AceptacionCredito
from app.models.amortizacion import CuotaAmortizacion
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.evaluacion import Evaluacion
from app.models.usuario import Usuario
from app.services import wompi_payout_service as wompi
from app.api.v1.endpoints import wompi_payouts


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PAYOUT_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PAYOUT_API_KEY", "sandbox-test-key")
    monkeypatch.setenv("WOMPI_PAYOUT_USER_PRINCIPAL_ID", "sandbox-test-principal")
    monkeypatch.setenv("WOMPI_PAYOUT_EVENTS_SECRET", "test_events_example")


def accepted_credit(amount=Decimal("100000.00")):
    db = TestSessionLocal()
    try:
        actor = db.query(Usuario).filter_by(email="bypass_admin@credifresh.com").one()
        customer = Cliente(nombre="Cliente ficticio", cedula=uuid4().hex[:12], telefono="3000000000")
        db.add(customer)
        db.flush()
        credit = Credito(cliente_id=customer.id, monto=amount, plazo_meses=1,
                          tasa_interes=Decimal("0.00"), estado="APROBADO")
        db.add(credit)
        db.flush()
        db.add(Evaluacion(credito_id=credit.id, decision="APROBADO", cuota_mensual=amount, motivos="Prueba"))
        db.add(AceptacionCredito(credito_id=credit.id, cliente_id=customer.id, usuario_id=actor.id,
                                monto=amount, plazo_meses=1, tasa_interes=Decimal("0.00"),
                                cuota_mensual=amount, total_estimado=amount,
                                condiciones_version="1.0"))
        db.commit()
        return credit.id
    finally:
        db.close()


def credit_state(credito_id):
    db = TestSessionLocal()
    try:
        return (db.query(Credito).filter_by(id=credito_id).one().estado,
                db.query(CuotaAmortizacion).filter_by(credito_id=credito_id).count())
    finally:
        db.close()


def payload(status="APPROVED"):
    return {"accountId": "sandbox_account", "bankId": "sandbox-bank", "transactionStatus": status}


def test_aprobado_una_sola_vez_y_sin_datos_reales(client, sandbox, monkeypatch):
    credit_id = accepted_credit()
    calls = []
    def create(body, reference):
        calls.append((body, reference))
        return {"data": {"id": "payout-approved"}}
    monkeypatch.setattr(wompi, "crear_lote_sandbox", create)
    monkeypatch.setattr(wompi, "consultar_transaccion_sandbox", lambda reference: {
        "transacciones": [{"reference": reference, "status": "APPROVED", "amountInCents": 10000000}]})
    url = f"/integraciones/wompi/payouts/sandbox/creditos/{credit_id}/desembolso"
    first = client.post(url, json=payload())
    assert first.status_code == 202, first.text
    assert first.json()["estado"] == "APROBADO"
    assert credit_state(credit_id) == ("DESEMBOLSADO", 1)
    assert calls[0][0]["transactions"][0]["name"] == "Cliente Sandbox"
    assert calls[0][0]["transactions"][0]["accountNumber"] == "00000000"
    assert client.post(url, json=payload()).json()["estado"] == "APROBADO"
    assert client.post(f"/integraciones/wompi/payouts/sandbox/creditos/{credit_id}/reconciliar").json()["estado"] == "APROBADO"
    assert len(calls) == 1
    assert credit_state(credit_id) == ("DESEMBOLSADO", 1)


def test_rechazado_no_desembolsa_y_no_reenvia(client, sandbox, monkeypatch):
    credit_id = accepted_credit()
    calls = []
    monkeypatch.setattr(wompi, "crear_lote_sandbox", lambda body, ref: calls.append(ref) or {"data": {"id": "payout-failed"}})
    monkeypatch.setattr(wompi, "consultar_transaccion_sandbox", lambda reference: {
        "transacciones": [{"reference": reference, "status": "FAILED", "amountInCents": 10000000}]})
    url = f"/integraciones/wompi/payouts/sandbox/creditos/{credit_id}/desembolso"
    assert client.post(url, json=payload("FAILED")).json()["estado"] == "RECHAZADO"
    assert client.post(url, json=payload("FAILED")).json()["estado"] == "RECHAZADO"
    assert credit_state(credit_id) == ("APROBADO", 0)
    assert len(calls) == 1


def test_webhook_reconsulta_y_es_idempotente(client, sandbox, monkeypatch):
    credit_id = accepted_credit()
    state = {"value": "PENDING"}
    monkeypatch.setattr(wompi, "crear_lote_sandbox", lambda *_: {"data": {"id": "payout-webhook"}})
    monkeypatch.setattr(wompi, "consultar_transaccion_sandbox", lambda reference: {
        "transacciones": [{"reference": reference, "status": state["value"], "amountInCents": 10000000}]})
    url = f"/integraciones/wompi/payouts/sandbox/creditos/{credit_id}/desembolso"
    assert client.post(url, json=payload()).json()["estado"] == "PENDIENTE"
    assert credit_state(credit_id) == ("APROBADO", 0)
    event = {"event": "payout.updated", "data": {"payout": {"id": "payout-webhook", "status": "TOTAL_PAYMENT", "amountInCents": 10000000}},
             "signature": {"properties": ["payout.id", "payout.status", "payout.amountInCents"]}, "timestamp": 1000}
    event["signature"]["checksum"] = hashlib.sha256(b"payout-webhookTOTAL_PAYMENT100000001000test_events_example").hexdigest()
    state["value"] = "APPROVED"
    route = "/integraciones/wompi/payouts/sandbox/eventos"
    assert client.post(route, json=event, headers={"X-Event-Checksum": "0" * 64}).status_code == 401
    assert credit_state(credit_id) == ("APROBADO", 0)
    assert client.post(route, json=event).status_code == 200
    assert client.post(route, json=event).status_code == 200
    assert credit_state(credit_id) == ("DESEMBOLSADO", 1)


def test_envio_incierto_no_repite_y_puede_reconciliarse(client, sandbox, monkeypatch):
    credit_id = accepted_credit()
    calls = []
    def timeout(*_):
        calls.append(1)
        raise HTTPException(status_code=502, detail="timeout")
    monkeypatch.setattr(wompi, "crear_lote_sandbox", timeout)
    url = f"/integraciones/wompi/payouts/sandbox/creditos/{credit_id}/desembolso"
    assert client.post(url, json=payload()).json()["estado"] == "ENVIO_INCIERTO"
    assert client.post(url, json=payload()).json()["estado"] == "ENVIO_INCIERTO"
    assert len(calls) == 1
    assert credit_state(credit_id) == ("APROBADO", 0)
    monkeypatch.setattr(wompi, "consultar_transaccion_sandbox", lambda reference: {
        "transacciones": [{"reference": reference, "status": "APPROVED", "amountInCents": 10000000}]})
    response = client.post(f"/integraciones/wompi/payouts/sandbox/creditos/{credit_id}/reconciliar")
    assert response.json()["estado"] == "APROBADO"
    assert credit_state(credit_id) == ("DESEMBOLSADO", 1)


def test_reconciliar_lote_aceptado_sin_id_en_respuesta_post(client, sandbox, monkeypatch):
    credit_id = accepted_credit()
    references = {}

    def create(body, _reference):
        references["transaction"] = body["transactions"][0]["reference"]
        return {"data": {}}

    monkeypatch.setattr(wompi, "crear_lote_sandbox", create)
    monkeypatch.setattr(wompi, "consultar_transaccion_sandbox", lambda _reference: {"transacciones": []})
    monkeypatch.setattr(wompi, "consultar_lote_sandbox", lambda reference: {
        "lotes": [{"id": "payout-found", "reference": reference}],
    })
    monkeypatch.setattr(wompi, "consultar_transacciones_lote_sandbox", lambda payout_id: {
        "transacciones": [{"reference": references["transaction"], "amountInCents": 10000000,
                           "status": "APPROVED"}],
    } if payout_id == "payout-found" else {"transacciones": []})
    response = client.post(
        f"/integraciones/wompi/payouts/sandbox/creditos/{credit_id}/desembolso",
        json=payload(),
    )
    assert response.status_code == 202, response.text
    assert response.json()["estado"] == "APROBADO"
    assert credit_state(credit_id) == ("DESEMBOLSADO", 1)


def test_monto_incorrecto_no_desembolsa_y_produccion_bloqueada(client, sandbox, monkeypatch):
    credit_id = accepted_credit()
    monkeypatch.setattr(wompi, "crear_lote_sandbox", lambda *_: {"data": {"id": "payout-mismatch"}})
    monkeypatch.setattr(wompi, "consultar_transaccion_sandbox", lambda reference: {
        "transacciones": [{"reference": reference, "status": "APPROVED", "amountInCents": 1}]})
    url = f"/integraciones/wompi/payouts/sandbox/creditos/{credit_id}/desembolso"
    assert client.post(url, json=payload()).json()["estado"] == "PENDIENTE"
    assert client.post(f"/integraciones/wompi/payouts/sandbox/creditos/{credit_id}/reconciliar").status_code == 409
    assert credit_state(credit_id) == ("APROBADO", 0)
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.post(url, json=payload()).status_code == 503


def test_notificacion_llega_antes_de_la_respuesta_sin_revertir_estado(client, sandbox, monkeypatch):
    credit_id = accepted_credit()
    monkeypatch.setattr(wompi, "consultar_transaccion_sandbox", lambda reference: {
        "transacciones": [{"reference": reference, "status": "APPROVED", "amountInCents": 10000000}]})
    def create(body, _reference):
        event = {"event": "payout.updated", "data": {"payout": {"id": "early-payout", "reference": body["reference"],
                 "status": "TOTAL_PAYMENT", "amountInCents": 10000000}},
                 "signature": {"properties": ["payout.id", "payout.status", "payout.amountInCents"]}, "timestamp": 1000}
        event["signature"]["checksum"] = hashlib.sha256(b"early-payoutTOTAL_PAYMENT100000001000test_events_example").hexdigest()
        inner_db = TestSessionLocal()
        try:
            assert asyncio.run(wompi_payouts.recibir_evento_payout_sandbox(event, None, inner_db))["recibido"]
        finally:
            inner_db.close()
        return {"data": {"id": "early-payout"}}
    monkeypatch.setattr(wompi, "crear_lote_sandbox", create)
    response = client.post(f"/integraciones/wompi/payouts/sandbox/creditos/{credit_id}/desembolso", json=payload())
    assert response.status_code == 202, response.text
    assert response.json()["estado"] == "APROBADO"
    assert credit_state(credit_id) == ("DESEMBOLSADO", 1)


def test_condiciones_cambiadas_exigen_revision_sin_marcar_aprobado(client, sandbox, monkeypatch):
    credit_id = accepted_credit()
    current = {"status": "PENDING"}
    monkeypatch.setattr(wompi, "crear_lote_sandbox", lambda *_: {"data": {"id": "payout-changed"}})
    monkeypatch.setattr(wompi, "consultar_transaccion_sandbox", lambda ref: {
        "transacciones": [{"reference": ref, "status": current["status"], "amountInCents": 10000000}]})
    url = f"/integraciones/wompi/payouts/sandbox/creditos/{credit_id}/desembolso"
    assert client.post(url, json=payload()).json()["estado"] == "PENDIENTE"
    db = TestSessionLocal()
    try:
        credit = db.query(Credito).filter_by(id=credit_id).one()
        credit.tasa_interes = Decimal("1.00")
        db.commit()
    finally:
        db.close()
    current["status"] = "APPROVED"
    result = client.post(f"/integraciones/wompi/payouts/sandbox/creditos/{credit_id}/reconciliar")
    assert result.status_code == 200, result.text
    assert result.json()["estado"] == "REVISION_MANUAL"
    assert credit_state(credit_id) == ("APROBADO", 0)


def test_cliente_no_puede_iniciar_desembolso(client, sandbox, monkeypatch):
    from main import app
    from app.core.deps import get_current_active_user
    monkeypatch.setitem(app.dependency_overrides, get_current_active_user,
                        lambda: Usuario(id=1234, email="cliente@example.invalid", rol="CLIENTE", activo=True))
    response = client.post("/integraciones/wompi/payouts/sandbox/creditos/123/desembolso", json=payload())
    assert response.status_code == 403


def test_no_permite_registrar_manual_en_sandbox_wompi(client, sandbox):
    credit_id = accepted_credit()
    response = client.post(f"/creditos/{credit_id}/desembolsar")
    assert response.status_code == 409
    assert credit_state(credit_id) == ("APROBADO", 0)


def test_catalogos_no_devuelven_datos_de_cuenta(client, sandbox, monkeypatch):
    monkeypatch.setattr(wompi_payouts, "listar_cuentas_sandbox", lambda: {"data": {"accounts": [
        {"id": "account-test", "accountNumber": "1234567890", "balanceInCents": 1000000}]}})
    monkeypatch.setattr(wompi_payouts, "listar_bancos_sandbox", lambda: {"data": {"banks": [
        {"id": "bank-test", "name": "Banco de prueba"}]}})
    response = client.get("/integraciones/wompi/payouts/sandbox/catalogos")
    assert response.status_code == 200
    assert response.json() == {"cuentas": [{"id": "account-test", "nombre": "Cuenta de prueba 1", "saldo_centavos": 1000000}],
                               "bancos": [{"id": "bank-test", "nombre": "Banco de prueba"}]}
    assert "1234567890" not in response.text


def test_formulario_de_pruebas_solo_se_anuncia_en_sandbox(client, sandbox, monkeypatch):
    assert client.get('/creditos/estado-operaciones').json()['desembolsos_wompi_sandbox'] is True
    monkeypatch.setenv('ENVIRONMENT', 'production')
    assert client.get('/creditos/estado-operaciones').json()['desembolsos_wompi_sandbox'] is False


def test_rango_de_solicitudes_de_la_app_en_sandbox(client, sandbox, monkeypatch):
    good = accepted_credit(Decimal("500000.00"))
    too_large = accepted_credit(Decimal("1500000.01"))
    calls = []
    monkeypatch.setattr(wompi, "crear_lote_sandbox", lambda body, ref: calls.append(body) or {"data": {"id": "payout-range"}})
    monkeypatch.setattr(wompi, "consultar_transaccion_sandbox", lambda ref: {"transacciones": []})
    base = "/integraciones/wompi/payouts/sandbox/creditos"
    assert client.post(f"{base}/{good}/desembolso", json=payload()).status_code == 202
    assert calls[0]["transactions"][0]["amount"] == 50000000
    assert client.post(f"{base}/{too_large}/desembolso", json=payload()).status_code == 422
    assert len(calls) == 1
