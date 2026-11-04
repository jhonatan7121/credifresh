import hashlib
import json
from io import BytesIO

import pytest
from fastapi import HTTPException

from app.services import wompi_payout_service as payouts


def set_sandbox(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PAYOUT_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PAYOUT_API_KEY", "sandbox-api-key-for-test")
    monkeypatch.setenv("WOMPI_PAYOUT_USER_PRINCIPAL_ID", "sandbox-principal-for-test")
    monkeypatch.setenv("WOMPI_PAYOUT_EVENTS_SECRET", "test_events_sandbox-for-test")


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def test_create_payout_uses_sandbox_headers_and_idempotency(monkeypatch):
    set_sandbox(monkeypatch)
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse({"data": {"id": "sandbox-payout-id", "status": "APPROVED"}})

    monkeypatch.setattr(payouts.urllib.request, "urlopen", fake_urlopen)
    result = payouts.crear_lote_sandbox(
        {"reference": "test-batch-001", "transactionStatus": "APPROVED", "transactions": []},
        "test-batch-001",
    )

    request = captured["request"]
    assert request.full_url == "https://api.sandbox.payouts.wompi.co/v1/payouts"
    assert request.get_header("X-api-key") == "sandbox-api-key-for-test"
    assert request.get_header("User-principal-id") == "sandbox-principal-for-test"
    assert request.get_header("Idempotency-key") == "test-batch-001"
    assert json.loads(request.data) == {"reference": "test-batch-001", "transactionStatus": "APPROVED", "transactions": []}
    assert result["data"]["id"] == "sandbox-payout-id"


def test_payout_service_fails_closed_outside_sandbox(monkeypatch):
    set_sandbox(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(HTTPException) as exc:
        payouts._sandbox_credentials()
    assert exc.value.status_code == 503


def test_invalid_idempotency_key_is_rejected(monkeypatch):
    set_sandbox(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        payouts._request("POST", "/payouts", payload={}, idempotency_key="invalid key")
    assert exc.value.status_code == 422


def test_payout_webhook_signature_uses_declared_properties(monkeypatch):
    set_sandbox(monkeypatch)
    event = {
        "event": "payout.updated",
        "data": {"payout": {"id": "sandbox-payout-id", "status": "TOTAL_PAYMENT", "amountInCents": 100000}},
        "signature": {"properties": ["payout.id", "payout.status", "payout.amountInCents"]},
        "timestamp": 1793650000,
    }
    signed = "sandbox-payout-idTOTAL_PAYMENT1000001793650000test_events_sandbox-for-test"
    checksum = hashlib.sha256(signed.encode()).hexdigest()
    event["signature"]["checksum"] = checksum

    assert payouts.validar_firma_evento_payout(event, checksum)
    assert not payouts.validar_firma_evento_payout(event, "0" * 64)


def test_payout_sandbox_accepts_dashboard_events_secret_prefix(monkeypatch):
    set_sandbox(monkeypatch)
    secret = "prod_events_sandbox-secret-for-test"
    monkeypatch.setenv("WOMPI_PAYOUT_EVENTS_SECRET", secret)
    event = {
        "event": "transaction.updated",
        "data": {"transaction": {"id": "sandbox-tx", "status": "APPROVED", "amountInCents": 100000}},
        "signature": {"properties": ["transaction.id", "transaction.status", "transaction.amountInCents"]},
        "timestamp": 1793650000,
    }
    signed = f"sandbox-txAPPROVED1000001793650000{secret}"
    checksum = hashlib.sha256(signed.encode()).hexdigest()
    event["signature"]["checksum"] = checksum

    assert payouts.validar_firma_evento_payout(event, checksum)


def test_payout_service_rejects_unknown_event_secret_prefix(monkeypatch):
    set_sandbox(monkeypatch)
    monkeypatch.setenv("WOMPI_PAYOUT_EVENTS_SECRET", "unknown_events_for-test")
    with pytest.raises(HTTPException) as exc:
        payouts._sandbox_credentials()
    assert exc.value.status_code == 503
