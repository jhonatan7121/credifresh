import hashlib

import pytest
from fastapi import HTTPException

from app.services.wompi_service import crear_link_pago, validar_firma_evento


def make_event(secret: str):
    event = {
        "event": "transaction.updated",
        "data": {"transaction": {
            "id": "sandbox-tx-001",
            "status": "APPROVED",
            "amount_in_cents": 125000,
            "currency": "COP",
            "payment_link_id": "sandbox-link-001",
        }},
        "environment": "test",
        "signature": {"properties": [
            "transaction.id", "transaction.status", "transaction.amount_in_cents",
        ]},
        "timestamp": 1792600000,
    }
    signed = "sandbox-tx-001APPROVED1250001792600000" + secret
    event["signature"]["checksum"] = hashlib.sha256(signed.encode()).hexdigest()
    return event


def test_validar_firma_evento_valida(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_test_fake")
    monkeypatch.setenv("WOMPI_EVENTS_SECRET", "test_events_fake")
    event = make_event("test_events_fake")
    assert validar_firma_evento(event, event["signature"]["checksum"])


def test_validar_firma_evento_rechaza_checksum_alterado(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_test_fake")
    monkeypatch.setenv("WOMPI_EVENTS_SECRET", "test_events_fake")
    event = make_event("test_events_fake")
    event["data"]["transaction"]["amount_in_cents"] = 999
    assert not validar_firma_evento(event)


def test_crear_link_requiere_claves_de_sandbox(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "production")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_prod_not-used")
    monkeypatch.setenv("WOMPI_EVENTS_SECRET", "prod_events_not-used")
    with pytest.raises(HTTPException) as exc:
        crear_link_pago(referencia="test-ref", credito_id=1, numero_cuota=1, monto=1250)
    assert exc.value.status_code == 503


def test_sandbox_bloqueado_en_backend_produccion(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_test_fake")
    monkeypatch.setenv("WOMPI_EVENTS_SECRET", "test_events_fake")
    with pytest.raises(HTTPException) as exc:
        crear_link_pago(referencia="test-ref", credito_id=1, numero_cuota=1, monto=1250)
    assert exc.value.status_code == 503
    assert "bloqueado" in exc.value.detail


def test_validacion_webhook_sandbox_bloqueada_en_backend_produccion(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_test_fake")
    monkeypatch.setenv("WOMPI_EVENTS_SECRET", "test_events_fake")
    with pytest.raises(HTTPException) as exc:
        validar_firma_evento(make_event("test_events_fake"))
    assert exc.value.status_code == 503


def test_link_payload_uses_sandbox_and_private_test_key(monkeypatch):
    import json
    from unittest.mock import patch

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"data":{"id":"abc123"}}'

    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_test_fake")
    monkeypatch.setenv("WOMPI_EVENTS_SECRET", "test_events_fake")
    with patch("app.services.wompi_service.urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
        result = crear_link_pago(referencia="internal-ref", credito_id=5, numero_cuota=2, monto=1250)
    request = urlopen.call_args.args[0]
    body = json.loads(request.data.decode())
    assert request.full_url == "https://sandbox.wompi.co/v1/payment_links"
    assert request.get_header("Authorization") == "Bearer prv_test_fake"
    assert body["amount_in_cents"] == 125000
    assert body["sku"] == "internal-ref"
    assert body["single_use"] is True
    assert result["checkout_url"] == "https://checkout.wompi.co/l/abc123"
