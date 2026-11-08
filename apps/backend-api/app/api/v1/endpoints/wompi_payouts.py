"""Admin-only test harness for Wompi third-party payments in Sandbox."""

from typing import Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.deps import RoleChecker
from app.models.usuario import Usuario
from app.models.wompi_desembolso import WompiDesembolsoSandbox
from app.services import desembolso_wompi_sandbox as credit_payouts
from app.services import wompi_payout_service as payout_service
from app.services.wompi_payout_service import (
    crear_lote_sandbox,
    consultar_lote_sandbox,
    consultar_lote_por_id_sandbox,
    consultar_transacciones_lote_sandbox,
    consultar_transaccion_sandbox,
    listar_lotes_recientes_sandbox,
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


class DesembolsoCreditoSandbox(BaseModel):
    accountId: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9-]+$")
    bankId: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9-]+$")
    transactionStatus: Literal["APPROVED", "FAILED"]


@router.get("/catalogos")
def catalogos_desembolso_sandbox(_: Usuario = Depends(RoleChecker(["ADMIN"]))):
    """Expose only IDs and safe labels for the Sandbox payout form."""
    accounts = payout_service._records_from(listar_cuentas_sandbox(),
        collection_keys=("accounts", "items", "results", "content", "rows", "data"),
        singular_keys=("account",), record_keys=("id", "accountId"))
    banks = payout_service._records_from(listar_bancos_sandbox(),
        collection_keys=("banks", "items", "results", "content", "rows", "data"),
        singular_keys=("bank",), record_keys=("id", "bankId"))
    safe_accounts = []
    for index, item in enumerate(accounts, 1):
        record = payout_service._record_from(item, ("account",), ("id", "accountId"))
        value = payout_service._first_value(record, "id", "accountId")
        if value:
            # Only expose the available Sandbox balance, never account numbers
            # or beneficiary/account metadata from Wompi's response.
            balance = payout_service._first_value(record, "balanceInCents", "balance_in_cents")
            safe_accounts.append({
                "id": str(value),
                "nombre": f"Cuenta de prueba {index}",
                "saldo_centavos": int(balance) if balance is not None else None,
            })
    safe_banks = []
    for index, item in enumerate(banks, 1):
        record = payout_service._record_from(item, ("bank",), ("id", "bankId"))
        value = payout_service._first_value(record, "id", "bankId")
        name = payout_service._first_value(record, "name", "bankName", "nombre", "code")
        if value:
            safe_banks.append({"id": str(value), "nombre": str(name) if name else f"Banco {index}"})
    return {"cuentas": safe_accounts, "bancos": safe_banks}


@router.post("/creditos/{credito_id}/desembolso", status_code=202)
def iniciar_desembolso_credito_sandbox(
    credito_id: int, payload: DesembolsoCreditoSandbox,
    db: Session = Depends(get_db), actor: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    """Create one synthetic Wompi Sandbox payout for an accepted credit."""
    return credit_payouts.start(db, actor, credito_id, payload.accountId, payload.bankId, payload.transactionStatus)


@router.get("/creditos/{credito_id}/desembolso")
def consultar_desembolso_credito_sandbox(
    credito_id: int, db: Session = Depends(get_db), _: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    credit_payouts._sandbox_only()
    attempt = db.query(WompiDesembolsoSandbox).filter_by(credito_id=credito_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="No hay desembolso Sandbox para este crédito.")
    return credit_payouts.summary(attempt)


@router.post("/creditos/{credito_id}/reconciliar")
def reconciliar_desembolso_credito_sandbox(
    credito_id: int, db: Session = Depends(get_db), _: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    return credit_payouts.reconcile(db, credito_id)


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


@router.get("/lotes/recientes")
def listar_lotes_recientes_pago_sandbox(
    limit: int = Query(10, ge=1, le=10),
    page: int = Query(1, ge=1),
    _: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    """List recent Sandbox batches, returning no beneficiary or account details."""
    return listar_lotes_recientes_sandbox(limit=limit, page=page)


@router.get("/lotes/id/{payout_id}")
def consultar_lote_pago_sandbox_por_id(
    payout_id: str,
    _: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    """Query one Wompi Sandbox batch by provider ID; no beneficiary data is returned."""
    return consultar_lote_por_id_sandbox(payout_id)


@router.get("/lotes/id/{payout_id}/transactions")
def consultar_transacciones_lote_pago_sandbox(
    payout_id: str,
    _: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    """Query transactions for one Wompi Sandbox batch; no beneficiary data is returned."""
    return consultar_transacciones_lote_sandbox(payout_id)


@router.get("/transactions/{reference}")
def consultar_transaccion_pago_sandbox(
    reference: str,
    _: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    """Query Wompi Sandbox directly by transaction reference; no beneficiary data is returned."""
    return consultar_transaccion_sandbox(reference)


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
    payout_id = data.get("id") or data.get("payoutId") or data.get("payout_id")
    status = data.get("status") or data.get("state")
    return {
        "ambiente": "sandbox",
        "payout_id": payout_id,
        "referencia": payload.reference,
        # Do not echo the requested simulation status as if it were Wompi's
        # result. A successful HTTP response without an identifiable payout
        # must remain explicitly unconfirmed until it can be queried.
        "estado": status,
        "registrado_por_wompi": bool(payout_id or status),
        "transacciones_reportadas": data.get("totalTransactions") or data.get("total_transactions"),
    }


@router.post("/eventos", status_code=200)
async def recibir_evento_payout_sandbox(
    event: dict = Body(..., description="Evento payout.updated o transaction.updated enviado por Wompi."),
    x_event_checksum: str | None = Header(default=None, alias="X-Event-Checksum"),
    db: Session = Depends(get_db),
):
    if event.get("event") not in {"payout.updated", "transaction.updated"}:
        raise HTTPException(status_code=400, detail="Tipo de evento de Pagos a Terceros no reconocido.")
    if not validar_firma_evento_payout(event, x_event_checksum):
        raise HTTPException(status_code=401, detail="La firma del evento Sandbox no es válida.")
    data = event.get("data") or {}
    item = data.get("payout" if event["event"] == "payout.updated" else "transaction") if isinstance(data, dict) else None
    provider_id = (item.get("id") if event["event"] == "payout.updated" else item.get("payoutId")) if isinstance(item, dict) else None
    attempt = None
    if isinstance(provider_id, str) and provider_id:
        attempt = db.query(WompiDesembolsoSandbox).filter_by(payout_id=provider_id).first()
    # A payout webhook may arrive before POST /payouts returned its ID. Its
    # reference is only a lookup hint; reconciliation verifies the result via
    # Wompi's authenticated transaction endpoint, including amount/reference.
    reference = item.get("reference") if isinstance(item, dict) and event["event"] == "payout.updated" else None
    if not attempt and isinstance(reference, str) and reference:
        attempt = db.query(WompiDesembolsoSandbox).filter_by(referencia_lote=reference).first()
    if attempt:
        try:
            credit_payouts.reconcile(db, attempt.credito_id)
        except HTTPException as exc:
            db.rollback()
            raise HTTPException(status_code=503, detail="No fue posible reconciliar el desembolso Sandbox.") from exc
    return {"recibido": True, "evento": event["event"]}
