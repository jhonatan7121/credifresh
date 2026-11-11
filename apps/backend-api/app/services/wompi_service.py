import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
import urllib.parse
from decimal import Decimal

from fastapi import HTTPException


SANDBOX_API_BASE = "https://sandbox.wompi.co/v1"
PRODUCTION_API_BASE = "https://production.wompi.co/v1"
SANDBOX_CHECKOUT_BASE = "https://checkout.wompi.co/l/"


def _wompi_environment() -> str:
    environment = os.getenv("WOMPI_ENVIRONMENT", "sandbox").strip().lower()
    runtime_environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    if environment not in {"sandbox", "production"}:
        raise HTTPException(
            status_code=503, detail="WOMPI_ENVIRONMENT debe ser sandbox o production."
        )
    if environment == "sandbox" and runtime_environment in {"production", "prod"}:
        raise HTTPException(status_code=503, detail="Wompi Sandbox está bloqueado en el backend de producción.")
    if environment == "production" and runtime_environment not in {"production", "prod"}:
        raise HTTPException(status_code=503, detail="Wompi Producción solo está habilitado en el backend de producción.")
    if environment == "production" and os.getenv("WOMPI_PRODUCTION_ENABLED", "false").strip().lower() != "true":
        raise HTTPException(status_code=503, detail="La integración Wompi de producción no está habilitada explícitamente.")
    return environment


def get_wompi_environment() -> str:
    """Return the configured Wompi environment after enforcing runtime isolation."""
    return _wompi_environment()


def _private_key() -> tuple[str, str, str]:
    environment = _wompi_environment()
    private_key = os.getenv("WOMPI_PRIVATE_KEY", "").strip()
    expected_prefix = "prv_test_" if environment == "sandbox" else "prv_prod_"
    if not private_key.startswith(expected_prefix):
        raise HTTPException(status_code=503, detail="Configura la llave privada del ambiente Wompi seleccionado.")
    api_base = SANDBOX_API_BASE if environment == "sandbox" else PRODUCTION_API_BASE
    return environment, private_key, api_base


def _events_secret() -> tuple[str, str]:
    environment = _wompi_environment()
    events_secret = os.getenv("WOMPI_EVENTS_SECRET", "").strip()
    expected_prefix = "test_events_" if environment == "sandbox" else "prod_events_"
    if not events_secret.startswith(expected_prefix):
        raise HTTPException(status_code=503, detail="Configura el secreto de eventos del ambiente Wompi seleccionado.")
    return environment, events_secret


def verificar_configuracion_recaudo() -> None:
    """Validate the environment and key before persisting a reservation."""
    _private_key()


def crear_link_pago(*, referencia: str, credito_id: int, numero_cuota: int, monto: Decimal) -> dict:
    environment, private_key, api_base = _private_key()
    amount_in_cents = int((Decimal(str(monto)) * 100).quantize(Decimal("1")))
    if amount_in_cents <= 0:
        raise HTTPException(status_code=400, detail="El saldo pendiente de la cuota no es válido.")
    payload = {
        "name": f"CrediFresh - pago de cuota {numero_cuota}",
        "description": f"Pago de cuota {numero_cuota} del crédito {credito_id}",
        "single_use": True,
        "collect_shipping": False,
        "currency": "COP",
        "amount_in_cents": amount_in_cents,
        "sku": referencia,
    }
    request = urllib.request.Request(
        f"{api_base}/payment_links",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {private_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Expose only the upstream HTTP status for sandbox diagnostics; never
        # include the response body or request headers, which may contain data.
        raise HTTPException(
            status_code=502,
            detail=f"Wompi rechazó la creación del link de pago (HTTP {exc.code}).",
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="No fue posible conectar con Wompi.") from exc

    data = body.get("data") if isinstance(body, dict) else None
    link_id = data.get("id") if isinstance(data, dict) else None
    if not isinstance(link_id, str) or not link_id:
        raise HTTPException(status_code=502, detail="Wompi respondió sin un identificador de link válido.")
    return {
        "id": link_id,
        "checkout_url": f"{SANDBOX_CHECKOUT_BASE}{link_id}",
        "ambiente": environment,
    }


def consultar_transaccion(transaction_id: str) -> dict:
    """Read authoritative transaction data from Wompi using the backend key."""
    _, private_key, api_base = _private_key()
    if not isinstance(transaction_id, str) or not transaction_id or len(transaction_id) > 128:
        raise HTTPException(status_code=400, detail="Identificador de transacción inválido.")
    request = urllib.request.Request(
        f"{api_base}/transactions/{urllib.parse.quote(transaction_id, safe='')}",
        headers={"Authorization": f"Bearer {private_key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise HTTPException(status_code=502, detail="No fue posible confirmar la transacción con Wompi.") from exc
    transaction = body.get("data") if isinstance(body, dict) else None
    if not isinstance(transaction, dict) or transaction.get("id") != transaction_id:
        raise HTTPException(status_code=502, detail="Wompi no devolvió una transacción verificable.")
    return transaction


def consultar_reembolso_sandbox(refund_id: str) -> dict:
    """Diagnóstico de solo lectura; nunca devuelve credenciales ni cuerpo de error."""
    if os.getenv("ENVIRONMENT", "").strip().lower() != "sandbox":
        raise HTTPException(status_code=404, detail="Consulta disponible solo en Sandbox.")
    environment, private_key, api_base = _private_key()
    if environment != "sandbox" or api_base != SANDBOX_API_BASE:
        raise HTTPException(status_code=404, detail="Consulta disponible solo en Sandbox.")
    if not isinstance(refund_id, str) or not refund_id.isascii() or not refund_id.isdigit() or len(refund_id) > 15:
        raise HTTPException(status_code=422, detail="Identificador de reembolso inválido.")
    request = urllib.request.Request(f"{SANDBOX_API_BASE}/refunds/{refund_id}",
        headers={"Authorization": f"Bearer {private_key}", "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"respuesta_http_wompi": exc.code, "datos_confirmados": False}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return {"respuesta_http_wompi": None, "datos_confirmados": False}
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return {"respuesta_http_wompi": 200, "datos_confirmados": False}
    return {"respuesta_http_wompi": 200, "datos_confirmados": str(data.get("id")) == refund_id,
            "estado": data.get("status") if data.get("status") in ("APPROVED", "DECLINED", "ERROR", "CANCELLED") else None,
            "monto_centavos": data.get("amount_in_cents") if type(data.get("amount_in_cents")) is int else None,
            "transaction_id": data.get("transaction_id") if isinstance(data.get("transaction_id"), str) else None}


def solicitar_reembolso_sandbox(*, transaction_id: str, amount_in_cents: int, reference: str, scenario: str) -> dict:
    """Submit once; an ambiguous result must be reviewed rather than retried."""
    if os.getenv("ENVIRONMENT", "").strip().lower() != "sandbox":
        raise HTTPException(status_code=404, detail="Reembolsos de prueba disponibles solo en Sandbox.")
    environment, private_key, api_base = _private_key()
    if environment != "sandbox" or api_base != SANDBOX_API_BASE:
        raise HTTPException(status_code=404, detail="Reembolsos de prueba disponibles solo en Sandbox.")
    payload = {"transaction_id": transaction_id, "amount_in_cents": amount_in_cents,
               "reference": reference, "reason": "Prueba controlada CrediFresh", "test_scenario": scenario}
    request = urllib.request.Request(
        f"{SANDBOX_API_BASE}/refunds", data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {private_key}", "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise HTTPException(status_code=502, detail="No se confirmó la respuesta del reembolso de prueba.") from exc
    data = body.get("data") if isinstance(body, dict) else None
    if (not isinstance(data, dict) or data.get("transaction_id") != transaction_id
            or data.get("reference") != reference or type(data.get("amount_in_cents")) is not int
            or data.get("amount_in_cents") != amount_in_cents
            or data.get("status") not in {"APPROVED", "DECLINED", "ERROR", "CANCELLED"}):
        raise HTTPException(status_code=502, detail="Wompi no devolvió un reembolso verificable.")
    refund_id = data.get("v2_refund_id") or data.get("id")
    if refund_id is None or not str(refund_id) or len(str(refund_id)) > 128:
        raise HTTPException(status_code=502, detail="Wompi no devolvió un identificador de reembolso verificable.")
    return {"status": data["status"], "refund_id": str(refund_id)}


def _property_value(event: dict, property_path: str):
    parts = property_path.split(".")
    value = event.get("data", {})
    if parts and parts[0] == "transaction":
        value = value.get("transaction", {}) if isinstance(value, dict) else None
        parts = parts[1:]
    for part in parts:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def validar_firma_evento(event: dict, header_checksum: str | None = None) -> bool:
    environment, events_secret = _events_secret()
    expected_event_environment = "test" if environment == "sandbox" else "prod"
    if event.get("environment") != expected_event_environment:
        return False
    signature = event.get("signature")
    if not isinstance(signature, dict):
        return False
    properties = signature.get("properties")
    timestamp = event.get("timestamp")
    body_checksum = signature.get("checksum")
    if not isinstance(properties, list) or not properties or not isinstance(timestamp, (int, str)):
        return False
    if any(not isinstance(path, str) or not path for path in properties):
        return False
    if not isinstance(body_checksum, str) or not body_checksum:
        return False
    if header_checksum and not hmac.compare_digest(header_checksum.strip().lower(), body_checksum.lower()):
        return False
    values = [_property_value(event, path) for path in properties]
    if any(value is None for value in values):
        return False
    signed_content = "".join(str(value) for value in values) + str(timestamp) + events_secret
    expected = hashlib.sha256(signed_content.encode("utf-8")).hexdigest()
    provided = header_checksum or body_checksum
    return hmac.compare_digest(expected.lower(), provided.strip().lower())
