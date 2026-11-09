import hashlib
import json
from io import BytesIO

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import wompi_payouts as payout_routes
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


def test_payout_http_failure_logs_status_without_error_details(monkeypatch, caplog):
    set_sandbox(monkeypatch)

    def fail(request, timeout):
        raise payouts.urllib.error.HTTPError(request.full_url, 400, "private-error-data", {}, None)

    monkeypatch.setattr(payouts.urllib.request, "urlopen", fail)
    with pytest.raises(HTTPException):
        payouts.crear_lote_sandbox({"transactionStatus": "APPROVED"}, "test-reference")
    assert "payout creation returned HTTP 400" in caplog.text
    assert "private-error-data" not in caplog.text
    assert "sandbox-api-key-for-test" not in caplog.text
    assert "sandbox-principal-for-test" not in caplog.text


def test_payout_connection_failure_logs_type_without_details(monkeypatch, caplog):
    set_sandbox(monkeypatch)

    def fail(request, timeout):
        raise TimeoutError("private-error-data")

    monkeypatch.setattr(payouts.urllib.request, "urlopen", fail)
    with pytest.raises(HTTPException):
        payouts.crear_lote_sandbox({"transactionStatus": "APPROVED"}, "test-reference")
    assert "payout creation failed: TimeoutError" in caplog.text
    assert "private-error-data" not in caplog.text


def test_payout_logs_documented_error_code_but_not_provider_message(monkeypatch, caplog):
    set_sandbox(monkeypatch)

    def fail(request, timeout):
        body = BytesIO(json.dumps({"code": "EXC_008", "message": "private-beneficiary-data"}).encode())
        raise payouts.urllib.error.HTTPError(request.full_url, 400, "bad request", {}, body)

    monkeypatch.setattr(payouts.urllib.request, "urlopen", fail)
    with pytest.raises(HTTPException):
        payouts.crear_lote_sandbox({"transactionStatus": "APPROVED"}, "test-reference")
    assert "payout error code: EXC_008" in caplog.text
    assert "private-beneficiary-data" not in caplog.text
    assert "sandbox-api-key-for-test" not in caplog.text


def test_payout_never_logs_unrecognized_provider_code(monkeypatch, caplog):
    set_sandbox(monkeypatch)

    def fail(request, timeout):
        body = BytesIO(json.dumps({"code": "private-code-value"}).encode())
        raise payouts.urllib.error.HTTPError(request.full_url, 400, "bad request", {}, body)

    monkeypatch.setattr(payouts.urllib.request, "urlopen", fail)
    with pytest.raises(HTTPException):
        payouts.crear_lote_sandbox({"transactionStatus": "APPROVED"}, "test-reference")
    assert "private-code-value" not in caplog.text


def test_payout_logs_only_allowed_field_names_from_validation_error(monkeypatch, caplog):
    set_sandbox(monkeypatch)

    def fail(request, timeout):
        body = BytesIO(json.dumps({"message": "reference too long", "secret": "private-test-value"}).encode())
        raise payouts.urllib.error.HTTPError(request.full_url, 400, "bad request", {}, body)

    monkeypatch.setattr(payouts.urllib.request, "urlopen", fail)
    with pytest.raises(HTTPException):
        payouts.crear_lote_sandbox({"transactionStatus": "APPROVED"}, "test-reference")
    assert "payout error code" not in caplog.text
    assert "response mentioned fields: reference" in caplog.text
    assert "private-test-value" not in caplog.text
    assert "reference too long" not in caplog.text


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


def test_payout_route_does_not_echo_requested_status_as_wompi_result(monkeypatch):
    monkeypatch.setattr(payout_routes, "crear_lote_sandbox", lambda *_args: {})
    payload = payout_routes.LoteSandbox(
        reference="test-batch-unconfirmed",
        accountId="sandbox-account",
        transactionStatus="APPROVED",
        transactions=[{
            "bankId": "sandbox-bank",
            "amount": 100000,
            "reference": "test-transaction-unconfirmed",
        }],
    )

    result = payout_routes.crear_lote_pago_sandbox(payload, None)

    assert result["payout_id"] is None
    assert result["estado"] is None
    assert result["registrado_por_wompi"] is False
    assert "resultado_simulado" not in result


def test_payout_route_returns_only_actual_wompi_status(monkeypatch):
    monkeypatch.setattr(
        payout_routes,
        "crear_lote_sandbox",
        lambda *_args: {"data": {"id": "sandbox-id", "status": "PENDING", "totalTransactions": 1}},
    )
    payload = payout_routes.LoteSandbox(
        reference="test-batch-confirmed",
        accountId="sandbox-account",
        transactionStatus="APPROVED",
        transactions=[{
            "bankId": "sandbox-bank",
            "amount": 100000,
            "reference": "test-transaction-confirmed",
        }],
    )

    result = payout_routes.crear_lote_pago_sandbox(payload, None)

    assert result["payout_id"] == "sandbox-id"
    assert result["estado"] == "PENDING"
    assert result["registrado_por_wompi"] is True
    assert result["transacciones_reportadas"] == 1


def test_consultar_lote_acepta_envolturas_de_respuesta_anidadas(monkeypatch):
    set_sandbox(monkeypatch)
    monkeypatch.setattr(
        payouts,
        "_request",
        lambda *_args, **_kwargs: {
            "data": {
                "result": {
                    "payouts": [{
                        "payout": {
                            "id": "sandbox-payout-id",
                            "reference": "test-batch-002",
                            "status": "TOTAL_PAYMENT",
                            "amountInCents": 100000,
                            "totalTransactions": 1,
                        }
                    }]
                }
            }
        },
    )

    result = payouts.consultar_lote_sandbox("test-batch-002")

    assert result["encontrado"] is True
    assert result["lotes"] == [{
        "id": "sandbox-payout-id",
        "reference": "test-batch-002",
        "status": "TOTAL_PAYMENT",
        "amountInCents": 100000,
        "totalTransactions": 1,
        "createdAt": None,
    }]


def test_listar_lotes_y_transacciones_acepta_envolturas_anidadas(monkeypatch):
    set_sandbox(monkeypatch)
    responses = iter([
        {"data": {"data": {"items": [{
            "id": "sandbox-payout-id",
            "reference": "test-batch-003",
            "status": "TOTAL_PAYMENT",
            "totalTransactions": 1,
        }]}}},
        {"data": {"result": {"transactions": {"items": [{
            "transaction": {
                "id": "sandbox-transaction-id",
                "reference": "test-transaction-003",
                "status": "APPROVED",
                "amountInCents": 100000,
            }
        }]}}}},
    ])
    monkeypatch.setattr(payouts, "_request", lambda *_args, **_kwargs: next(responses))

    batches = payouts.listar_lotes_recientes_sandbox()
    transactions = payouts.consultar_transacciones_lote_sandbox("sandbox-payout-id")

    assert batches["lotes"][0]["reference"] == "test-batch-003"
    assert transactions["encontrado"] is True
    assert transactions["transacciones_reportadas"] == 1
    assert transactions["transacciones"][0]["status"] == "APPROVED"


def test_consultar_transaccion_acepta_transaccion_unica_anidada(monkeypatch):
    set_sandbox(monkeypatch)
    monkeypatch.setattr(
        payouts,
        "_request",
        lambda *_args, **_kwargs: {
            "data": {
                "result": {
                    "transaction": {
                        "id": "sandbox-transaction-id",
                        "reference": "test-transaction-004",
                        "status": "FAILED",
                        "amountInCents": 100000,
                        "payoutId": "sandbox-payout-id",
                    }
                }
            }
        },
    )

    result = payouts.consultar_transaccion_sandbox("test-transaction-004")

    assert result["encontrado"] is True
    assert result["transacciones"][0]["status"] == "FAILED"
