"""Wompi Pagos a Terceros client, deliberately restricted to Sandbox."""

import hashlib
import hmac
import json
import logging
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlencode
from urllib.parse import quote

from fastapi import HTTPException

SANDBOX_API_BASE = "https://api.sandbox.payouts.wompi.co/v1"
logger = logging.getLogger(__name__)
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_RESPONSE_ENVELOPE_KEYS = ("data", "result", "response", "payload", "_embedded")
_COLLECTION_KEYS = ("payouts", "transactions", "items", "results", "content", "records", "rows", "data")


def _first_value(record: dict, *keys: str):
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return None


def _record_from(value, singular_keys: tuple[str, ...], record_keys: tuple[str, ...], depth: int = 0) -> dict:
    """Unwrap a single Wompi record from common API response envelopes."""
    if depth > 6:
        return {}
    if isinstance(value, list):
        for item in value:
            record = _record_from(item, singular_keys, record_keys, depth + 1)
            if record:
                return record
        return {}
    if not isinstance(value, dict):
        return {}

    for key in singular_keys + _RESPONSE_ENVELOPE_KEYS:
        nested = value.get(key)
        if isinstance(nested, (dict, list)):
            record = _record_from(nested, singular_keys, record_keys, depth + 1)
            if record:
                return record
    if any(key in value for key in record_keys):
        return value
    return {}


def _records_from(value, collection_keys: tuple[str, ...], singular_keys: tuple[str, ...], record_keys: tuple[str, ...], depth: int = 0) -> list[dict]:
    """Find a record list through nested pagination and data envelopes."""
    if depth > 6:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []

    for key in collection_keys:
        nested = value.get(key)
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        if isinstance(nested, dict):
            records = _records_from(nested, collection_keys, singular_keys, record_keys, depth + 1)
            if records:
                return records

    for key in singular_keys:
        nested = value.get(key)
        if isinstance(nested, (dict, list)):
            record = _record_from(nested, singular_keys, record_keys, depth + 1)
            return [record] if record else []

    for key in _RESPONSE_ENVELOPE_KEYS:
        nested = value.get(key)
        if isinstance(nested, (dict, list)):
            records = _records_from(nested, collection_keys, singular_keys, record_keys, depth + 1)
            if records:
                return records

    if any(key in value for key in record_keys):
        return [value]
    return []


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
    # Wompi Pagos a Terceros exposes its event secret separately from the
    # collection integration. Its Sandbox dashboard can show a `prod_events_`
    # prefix, so the environment is determined by the isolated service and the
    # dedicated Sandbox API base URL, not by that prefix alone.
    if events_secret and not events_secret.startswith(("test_events_", "prod_events_")):
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
        if method == "POST" and path == "/payouts":
            logger.warning("Wompi Sandbox payout creation returned HTTP %d", exc.code)
        raise HTTPException(status_code=502, detail=f"Wompi Sandbox rechazó la solicitud (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        if method == "POST" and path == "/payouts":
            logger.warning("Wompi Sandbox payout creation failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="No fue posible conectar con Wompi Sandbox.") from exc
    if not isinstance(body, dict):
        if method == "POST" and path == "/payouts":
            logger.warning("Wompi Sandbox payout creation returned a non-object response")
        raise HTTPException(status_code=502, detail="Wompi Sandbox respondió con un formato inesperado.")
    return body


def listar_cuentas_sandbox() -> dict:
    return _request("GET", "/accounts")


def listar_bancos_sandbox() -> dict:
    return _request("GET", "/banks")


def consultar_lote_sandbox(reference: str) -> dict:
    """Query Wompi Sandbox by reference and return only non-sensitive batch fields."""
    if not _IDEMPOTENCY_RE.fullmatch(reference):
        raise HTTPException(status_code=422, detail="La referencia debe tener 1-64 letras, números o guiones.")
    response = _request("GET", f"/payouts?{urlencode({'reference': reference, 'limit': 10, 'page': 1})}")
    records = _records_from(
        response,
        collection_keys=("payouts", "items", "results", "content", "records", "rows", "data"),
        singular_keys=("payout",),
        record_keys=("id", "payoutId", "payout_id", "reference", "referenceId", "reference_id"),
    )

    matches = []
    for item in records:
        if not isinstance(item, dict):
            continue
        # A Wompi response may wrap the payout itself in `payout`.
        payout = _record_from(
            item,
            singular_keys=("payout",),
            record_keys=("id", "payoutId", "payout_id", "reference", "referenceId", "reference_id"),
        )
        item_reference = _first_value(payout, "reference", "referenceId", "reference_id")
        if item_reference != reference:
            continue
        matches.append({
            "id": _first_value(payout, "id", "payoutId", "payout_id"),
            "reference": item_reference,
            "status": _first_value(payout, "status", "state", "payoutStatus", "payout_status"),
            "amountInCents": _first_value(payout, "amountInCents", "amount_in_cents", "amount"),
            "totalTransactions": _first_value(payout, "totalTransactions", "total_transactions"),
            "createdAt": _first_value(payout, "createdAt", "created_at"),
        })

    return {"ambiente": "sandbox", "referencia": reference, "encontrado": bool(matches), "lotes": matches}


def consultar_lote_por_id_sandbox(payout_id: str) -> dict:
    """Query one Wompi Sandbox payout by its provider ID; omit beneficiary details."""
    if not _IDEMPOTENCY_RE.fullmatch(payout_id):
        raise HTTPException(status_code=422, detail="El ID del lote contiene caracteres no permitidos.")
    response = _request("GET", f"/payouts/{quote(payout_id, safe='')}")
    data = _record_from(
        response,
        singular_keys=("payout",),
        record_keys=("id", "payoutId", "payout_id", "reference", "referenceId", "reference_id", "status", "state"),
    )

    result_id = _first_value(data, "id", "payoutId", "payout_id")
    reference = _first_value(data, "reference", "referenceId", "reference_id")
    status = _first_value(data, "status", "state", "payoutStatus", "payout_status")
    return {
        "ambiente": "sandbox",
        "encontrado": bool(result_id or reference or status),
        "lote": {
            "id": result_id,
            "referencia": reference,
            "estado": status,
            "monto_centavos": _first_value(data, "amountInCents", "amount_in_cents", "amount"),
            "transacciones_reportadas": _first_value(data, "totalTransactions", "total_transactions"),
            "creado_en": _first_value(data, "createdAt", "created_at"),
        },
    }


def consultar_transacciones_lote_sandbox(payout_id: str) -> dict:
    """Query transactions for one Sandbox payout; omit beneficiary details."""
    if not _IDEMPOTENCY_RE.fullmatch(payout_id):
        raise HTTPException(status_code=422, detail="El ID del lote contiene caracteres no permitidos.")
    response = _request("GET", f"/payouts/{quote(payout_id, safe='')}/transactions")
    records = _records_from(
        response,
        collection_keys=("transactions", "items", "results", "content", "records", "rows", "data"),
        singular_keys=("transaction",),
        record_keys=("id", "transactionId", "transaction_id", "reference", "referenceId", "reference_id", "status", "state"),
    )

    transactions = []
    for item in records:
        if not isinstance(item, dict):
            continue
        transaction = _record_from(
            item,
            singular_keys=("transaction",),
            record_keys=("id", "transactionId", "transaction_id", "reference", "referenceId", "reference_id", "status", "state"),
        )
        transactions.append({
            "id": _first_value(transaction, "id", "transactionId", "transaction_id"),
            "reference": _first_value(transaction, "reference", "referenceId", "reference_id"),
            "status": _first_value(transaction, "status", "state", "transactionStatus", "transaction_status"),
            "amountInCents": _first_value(transaction, "amountInCents", "amount_in_cents", "amount"),
            "createdAt": _first_value(transaction, "createdAt", "created_at"),
        })

    return {
        "ambiente": "sandbox",
        "payout_id": payout_id,
        "encontrado": bool(transactions),
        "transacciones_reportadas": len(transactions),
        "transacciones": transactions,
    }


def listar_lotes_recientes_sandbox(limit: int = 10, page: int = 1) -> dict:
    """List recent Sandbox payouts with non-sensitive fields only."""
    response = _request("GET", f"/payouts?{urlencode({'limit': limit, 'page': page})}")
    records = _records_from(
        response,
        collection_keys=("payouts", "items", "results", "content", "records", "rows", "data"),
        singular_keys=("payout",),
        record_keys=("id", "payoutId", "payout_id", "reference", "referenceId", "reference_id"),
    )
    summaries = []
    for item in records:
        if not isinstance(item, dict):
            continue
        payout = _record_from(
            item,
            singular_keys=("payout",),
            record_keys=("id", "payoutId", "payout_id", "reference", "referenceId", "reference_id"),
        )
        summaries.append({
            "id": _first_value(payout, "id", "payoutId", "payout_id"),
            "reference": _first_value(payout, "reference", "referenceId", "reference_id"),
            "status": _first_value(payout, "status", "state", "payoutStatus", "payout_status"),
            "amountInCents": _first_value(payout, "amountInCents", "amount_in_cents", "amount"),
            "totalTransactions": _first_value(payout, "totalTransactions", "total_transactions"),
            "createdAt": _first_value(payout, "createdAt", "created_at"),
        })
    return {"ambiente": "sandbox", "lotes": summaries}


def consultar_transaccion_sandbox(reference: str) -> dict:
    """Query a Sandbox payout transaction by reference and return safe fields only."""
    if not _IDEMPOTENCY_RE.fullmatch(reference):
        raise HTTPException(status_code=422, detail="La referencia debe tener 1-64 letras, números o guiones.")
    response = _request("GET", f"/transactions/{quote(reference, safe='')}")
    records = _records_from(
        response,
        collection_keys=("transactions", "items", "results", "content", "records", "rows", "data"),
        singular_keys=("transaction",),
        record_keys=("id", "transactionId", "transaction_id", "reference", "referenceId", "reference_id"),
    )

    matches = []
    for item in records:
        if not isinstance(item, dict):
            continue
        transaction = _record_from(
            item,
            singular_keys=("transaction",),
            record_keys=("id", "transactionId", "transaction_id", "reference", "referenceId", "reference_id"),
        )
        item_reference = _first_value(transaction, "reference", "referenceId", "reference_id")
        if item_reference != reference:
            continue
        matches.append({
            "id": _first_value(transaction, "id", "transactionId", "transaction_id"),
            "reference": item_reference,
            "status": _first_value(transaction, "status", "state", "transactionStatus", "transaction_status"),
            "amountInCents": _first_value(transaction, "amountInCents", "amount_in_cents", "amount"),
            "payoutId": _first_value(transaction, "payoutId", "payout_id"),
            "createdAt": _first_value(transaction, "createdAt", "created_at"),
        })

    return {"ambiente": "sandbox", "referencia": reference, "encontrado": bool(matches), "transacciones": matches}


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
