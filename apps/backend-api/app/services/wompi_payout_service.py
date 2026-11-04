"""Wompi Pagos a Terceros client, deliberately restricted to Sandbox."""

import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.request

from fastapi import HTTPException

SANDBOX_API_BASE = "https://api.sandbox.payouts.wompi.co/v1"
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def _sandbox_credentials() -> tuple[str, str, str]:
    if os.getenv("ENVIRONMENT", "").strip().lower() != "sandbox":
        raise HTTPException(status_code=503, detail="Pagos a Terceros solo está habilitado en el servicio Sandbox.")
    if os.getenv("WOMPI_PAYOUT_ENVIRONMENT", "").strip().lower() != "sandbox":
        raise HTTPException(status_code=503, detail="El ambiente de Pagos a Terceros no está configurado como Sandbox.")
    api_key = os.getenv("WOMPI_PAYOUT_API_KEY", "").strip()
    principal_id = os.getenv("WOMPI_PAYOUT_USER_PRINCIPAL_ID", "").strip()
    events_secret = os.getenv("WOMPI_PAYOUT_EVENTS_SECRET", "").strip()
    if not api_key or not principal_id:
        raise HTTPException(status_code=503, detail="Faltan las credenciales Sandbox de Pagos a Terceros.")
    if events_secret and not events_secret.startswith("test_events_"):
        raise HTTPException(status_code=503, detail="El secreto de eventos no corresponde al ambiente Sandbox.")
    return api_key, principal_id, events_secret


def _request(method: str, path: str, *, payload: dict | None = None, idempotency_key: str | None = None) -> dict:
    api_key, principal_id, _ = _sandbox_credentials()
    headers = {"x-api-key": api_key, "user-principal-id": principal_id, "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if idempotency_key:
        if not _IDEMPOTENCY_RE.fullmatch(idempotency_key):
            raise HTTPException(status_code=422, detail="La referencia debe tener 1-64 letras, números o guiones.")
        headers["idempotency-key"] = idempotency_key
    request = urllib.request.Request(f"{SANDBOX_API_BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Wompi Sandbox rechazó la solicitud (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="No fue posible conectar con Wompi Sandbox.") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="Wompi Sandbox respondió con un formato inesperado.")
    return body


def listar_cuentas_sandbox() -> dict:
    return _request("GET", "/accounts")


def listar_bancos_sandbox() -> dict:
    return _request("GET", "/banks")


def crear_lote_sandbox(payload: dict, idempotency_key: str) -> dict:
    if payload.get("transactionStatus") not in {"APPROVED", "FAILED"}:
        raise HTTPException(status_code=422, detail="Indica transactionStatus como APPROVED o FAILED para simular el resultado.")
    return _request("POST", "/payouts", payload=payload, idempotency_key=idempotency_key)


def validar_firma_evento_payout(event: dict, header_checksum: str | None = None) -> bool:
    _, _, secret = _sandbox_credentials()
    if not secret:
        raise HTTPException(status_code=503, detail="Falta el secreto de eventos Sandbox de Pagos a Terceros.")
    signature = event.get("signature")
    timestamp = event.get("timestamp")
    if not isinstance(signature, dict) or not isinstance(timestamp, (int, str)):
        return False
    properties = signature.get("properties")
    checksum = signature.get("checksum")
    if not isinstance(properties, list) or not properties or not isinstance(checksum, str):
        return False
    if header_checksum and not hmac.compare_digest(header_checksum.strip().lower(), checksum.lower()):
        return False
    values = []
    for path in properties:
        parts = path.split(".")
        if parts and parts[0] == "data":
            parts = parts[1:]
        value = event.get("data")
        for part in parts:
            if not isinstance(value, dict):
                return False
            value = value.get(part)
        if value is None:
            return False
        values.append(str(value))
    signed = "".join(values) + str(timestamp) + secret
    expected = hashlib.sha256(signed.encode("utf-8")).hexdigest()
    provided = header_checksum or checksum
    return hmac.compare_digest(expected.lower(), provided.strip().lower())
