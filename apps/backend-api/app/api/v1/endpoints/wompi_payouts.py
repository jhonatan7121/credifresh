"""Admin-only test harness for Wompi third-party payments in Sandbox."""

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.core.deps import RoleChecker
from app.models.usuario import Usuario
from app.services.wompi_payout_service import (
    crear_lote_sandbox,
    consultar_lote_sandbox,
    listar_bancos_sandbox,
    listar_cuentas_sandbox,
    validar_firma_evento_payout,
)

router = APIRouter(prefix="/integraciones/wompi/payouts/sandbox", tags=["Wompi Pagos a Terceros Sandbox"])


class TransaccionSandbox(BaseModel):
    bankId: str = Field(min_length=1, max_length=80)
    amount: int = Field(gt=0, le=10_000_000, description="Centavos COP; máximo de prueba $100.000 COP")
    reference: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$")


class LoteSandbox(BaseModel):
    reference: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    accountId: str = Field(min_length=1, max_length=100)
    paymentType: Literal["OTHER"] = "OTHER"
    transactionStatus: Literal["APPROVED", "FAILED"]
    transactions: list[TransaccionSandbox] = Field(min_length=1, max_length=1)


@router.get("/accounts")
def cuentas_sandbox(_: Usuario = Depends(RoleChecker(["ADMIN"]))):
    return listar_cuentas_sandbox()


@router.get("/banks")
def bancos_sandbox(_: Usuario = Depends(RoleChecker(["ADMIN"]))):
    return listar_bancos_sandbox()


@router.get("/lotes")
def consultar_lote_pago_sandbox(
    reference: str = Query(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$"),
    _: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    """Consult Wompi Sandbox directly by batch reference; no beneficiary data is returned."""
    return consultar_lote_sandbox(reference)


@router.post("/lotes", status_code=201)
def crear_lote_pago_sandbox(payload: LoteSandbox, _: Usuario = Depends(RoleChecker(["ADMIN"]))):
    request_body = payload.model_dump()
    # Never accept or transmit user-provided beneficiary PII in this test harness.
    for transaction in request_body["transactions"]:
        transaction.update({
            "legalIdType": "CC",
            "legalId": "1000000000",
            "accountType": "AHORROS",
            "accountNumber": "00000000",
            "name": "Cliente Sandbox",
            "email": "cliente@credifresh.invalid",
        })
    result = crear_lote_sandbox(request_body, payload.reference)
    data = result.get("data", result)
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}
    if isinstance(data, dict) and isinstance(data.get("payout"), dict):
        data = data["payout"]
    if not isinstance(data, dict):
        data = {}
    return {
        "ambiente": "sandbox",
        "payout_id": data.get("id") or data.get("payoutId") or data.get("payout_id"),
        "referencia": payload.reference,
        "estado": data.get("status") or data.get("state"),
        "resultado_simulado": payload.transactionStatus,
        "transacciones": data.get("totalTransactions") or data.get("total_transactions") or 1,
    }


@router.post("/eventos", status_code=200)
async def recibir_evento_payout_sandbox(
    request: Request,
    x_event_checksum: str | None = Header(default=None, alias="X-Event-Checksum"),
):
    try:
        event = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="El evento no contiene JSON válido.") from exc
    if not isinstance(event, dict) or event.get("event") not in {"payout.updated", "transaction.updated"}:
        raise HTTPException(status_code=400, detail="Tipo de evento de Pagos a Terceros no reconocido.")
    if not validar_firma_evento_payout(event, x_event_checksum):
        raise HTTPException(status_code=401, detail="La firma del evento Sandbox no es válida.")
    return {"recibido": True, "evento": event["event"]}
