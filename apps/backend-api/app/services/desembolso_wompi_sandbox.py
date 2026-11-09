"""Credit disbursement reconciliation for the isolated Wompi Sandbox only."""
import datetime
import logging
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.aceptacion_credito import AceptacionCredito
from app.models.amortizacion import CuotaAmortizacion
from app.models.credito import Credito
from app.models.evaluacion import Evaluacion
from app.models.usuario import Usuario
from app.models.wompi_desembolso import WompiDesembolsoSandbox
from app.services import wompi_payout_service as wompi
from modules.audit.audit_service import registrar_auditoria
from modules.creditos.amortizacion_service import generar_plan_amortizacion

logger = logging.getLogger(__name__)


def _sandbox_only():
    # This validates both isolated environment flags and payout credentials.
    wompi._sandbox_credentials()


def _validate_credit(db: Session, credito_id: int) -> Credito:
    credit = db.query(Credito).filter(Credito.id == credito_id).with_for_update().first()
    if not credit:
        raise HTTPException(status_code=404, detail="Crédito no encontrado.")
    if credit.estado != "APROBADO":
        raise HTTPException(status_code=409, detail="El crédito debe estar aprobado y sin desembolso.")
    if db.query(CuotaAmortizacion).filter_by(credito_id=credit.id).first():
        raise HTTPException(status_code=409, detail="El crédito ya tiene cuotas generadas.")
    acceptance = db.query(AceptacionCredito).filter_by(credito_id=credit.id, cliente_id=credit.cliente_id).first()
    evaluation = (db.query(Evaluacion).filter_by(credito_id=credit.id)
                  .order_by(Evaluacion.fecha_evaluacion.desc(), Evaluacion.id.desc()).first())
    if not acceptance or not evaluation or evaluation.decision != "APROBADO" or evaluation.cuota_mensual is None:
        raise HTTPException(status_code=409, detail="El crédito requiere evaluación aprobada y condiciones aceptadas.")
    installments = generar_plan_amortizacion(credito=credit, evaluacion=evaluation, fecha_desembolso=datetime.datetime.now(datetime.timezone.utc))
    values = {
        "monto": Decimal(str(credit.monto)),
        "plazo_meses": credit.plazo_meses,
        "tasa_interes": Decimal(str(credit.tasa_interes)),
        "cuota_mensual": Decimal(str(evaluation.cuota_mensual)),
        "total_estimado": sum((Decimal(str(item.monto_cuota)) for item in installments), Decimal("0.00")),
    }
    if any(getattr(acceptance, key) != value for key, value in values.items()):
        raise HTTPException(status_code=409, detail="Las condiciones actuales no coinciden con las aceptadas.")
    return credit


def summary(attempt: WompiDesembolsoSandbox) -> dict:
    return {
        "ambiente": "sandbox", "credito_id": attempt.credito_id,
        "referencia_lote": attempt.referencia_lote,
        "referencia_transaccion": attempt.referencia_transaccion,
        "payout_id": attempt.payout_id, "monto_centavos": attempt.monto_centavos,
        "estado": attempt.estado,
    }


def start(db: Session, actor: Usuario, credito_id: int, account_id: str, bank_id: str, simulated_status: str) -> dict:
    _sandbox_only()
    existing = db.query(WompiDesembolsoSandbox).filter_by(credito_id=credito_id).first()
    if existing:
        return summary(existing)
    credit = _validate_credit(db, credito_id)
    existing = db.query(WompiDesembolsoSandbox).filter_by(credito_id=credito_id).first()
    if existing:
        return summary(existing)
    cents = Decimal(str(credit.monto)) * 100
    if cents != cents.to_integral_value() or cents <= 0 or cents > 150_000_000:
        raise HTTPException(status_code=422, detail="El monto de prueba debe ser positivo y no superar $1.500.000 COP.")
    identifier = uuid4().hex
    attempt = WompiDesembolsoSandbox(
        credito_id=credit.id, usuario_id=actor.id, referencia_lote=f"CF-SBX-{identifier}",
        referencia_transaccion=f"TX-{identifier}", monto_centavos=int(cents), estado="ENVIANDO",
    )
    db.add(attempt)
    registrar_auditoria(db, actor, "INICIAR_DESEMBOLSO_WOMPI_SANDBOX", "credito", credit.id,
                        resultado="EN_PROCESO", detalles={"referencia": attempt.referencia_lote})
    try:
        # Persist before the network request so an uncertain response can never
        # cause an automatic second transfer for the same credit.
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(WompiDesembolsoSandbox).filter_by(credito_id=credito_id).first()
        if existing:
            return summary(existing)
        raise
    db.refresh(attempt)
    payload = {
        "reference": attempt.referencia_lote, "accountId": account_id,
        "paymentType": "OTHER", "transactionStatus": simulated_status,
        "transactions": [{"legalIdType": "CC", "legalId": "1000000000", "bankId": bank_id,
                          "accountType": "AHORROS", "accountNumber": "00000000", "name": "Cliente Sandbox",
                          "email": "cliente@credifresh.invalid", "amount": attempt.monto_centavos,
                          "reference": attempt.referencia_transaccion}],
    }
    try:
        response = wompi.crear_lote_sandbox(payload, attempt.referencia_lote)
        record = wompi._record_from(response, singular_keys=("payout",), record_keys=("id", "payoutId", "payout_id"))
        provider_id = wompi._first_value(record, "id", "payoutId", "payout_id")
        if not provider_id:
            logger.warning("Wompi Sandbox payout creation returned no payout identifier")
        # A webhook can arrive before POST returns. Reload under lock so that
        # its terminal decision cannot be overwritten by this response.
        attempt = (db.query(WompiDesembolsoSandbox).filter_by(credito_id=credito_id)
                   .populate_existing().with_for_update().one())
        attempt.payout_id = str(provider_id) if provider_id else None
        if attempt.estado not in {"APROBADO", "RECHAZADO", "REVISION_MANUAL"}:
            attempt.estado = "PENDIENTE" if provider_id else "ENVIO_INCIERTO"
        db.commit()
    except (HTTPException, OSError, ValueError):
        db.rollback()
        attempt = (db.query(WompiDesembolsoSandbox).filter_by(credito_id=credito_id)
                   .populate_existing().with_for_update().one())
        if attempt.estado not in {"APROBADO", "RECHAZADO", "REVISION_MANUAL"}:
            attempt.estado = "ENVIO_INCIERTO"
        db.commit()
        return summary(attempt)
    try:
        return reconcile(db, credito_id)
    except HTTPException:
        db.rollback()
        attempt = db.query(WompiDesembolsoSandbox).filter_by(credito_id=credito_id).first()
        return summary(attempt)


def reconcile(db: Session, credito_id: int) -> dict:
    _sandbox_only()
    attempt = db.query(WompiDesembolsoSandbox).filter_by(credito_id=credito_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="No hay desembolso Sandbox para este crédito.")
    if attempt.estado in {"APROBADO", "RECHAZADO", "REVISION_MANUAL"}:
        return summary(attempt)
    reference, expected = attempt.referencia_transaccion, attempt.monto_centavos
    provider = wompi.consultar_transaccion_sandbox(reference)
    matches = provider.get("transacciones", [])
    if len(matches) != 1:
        # The batch may be accepted before Wompi publishes its individual
        # transaction. Search by our exact stored reference, then query the
        # matched batch details instead of ever resending the payout.
        batch_response = wompi.consultar_lote_sandbox(attempt.referencia_lote)
        batches = [item for item in batch_response.get("lotes", [])
                   if item.get("reference") == attempt.referencia_lote]
        if len(batches) != 1:
            return summary(attempt)
        batch_id = batches[0].get("id")
        if not batch_id:
            return summary(attempt)
        attempt.payout_id = str(batch_id)
        attempt.estado = "PENDIENTE"
        db.commit()
        transaction_response = wompi.consultar_transacciones_lote_sandbox(str(batch_id))
        matches = [item for item in transaction_response.get("transacciones", [])
                   if item.get("reference") == reference]
        if len(matches) != 1:
            return summary(attempt)
    transaction = matches[0]
    if transaction.get("reference") != reference or transaction.get("amountInCents") != expected:
        raise HTTPException(status_code=409, detail="El resultado de Wompi no coincide con la referencia y el monto esperados.")
    state = str(transaction.get("status") or "").upper()
    if state not in {"APPROVED", "FAILED", "REJECTED", "DECLINED", "CANCELLED"}:
        return summary(attempt)
    attempt = db.query(WompiDesembolsoSandbox).filter_by(credito_id=credito_id).populate_existing().with_for_update().first()
    if attempt.estado in {"APROBADO", "RECHAZADO", "REVISION_MANUAL"}:
        return summary(attempt)
    if state != "APPROVED":
        attempt.estado = "RECHAZADO"
        actor = db.query(Usuario).filter_by(id=attempt.usuario_id).first()
        registrar_auditoria(db, actor, "DESEMBOLSO_WOMPI_SANDBOX_RECHAZADO", "credito", credito_id,
                            resultado="RECHAZADO", detalles={"referencia": attempt.referencia_lote})
        db.commit()
        return summary(attempt)
    actor = db.query(Usuario).filter_by(id=attempt.usuario_id).first()
    if not actor:
        attempt.estado = "REVISION_MANUAL"
        db.commit()
        return summary(attempt)
    try:
        # The existing credit operation commits the credit, installments and
        # this attempt together in one database transaction.
        from app.api.v1.endpoints.creditos import finalizar_desembolso_confirmado
        finalizar_desembolso_confirmado(credito_id, db, actor, on_success=lambda: setattr(attempt, "estado", "APROBADO"))
    except HTTPException:
        db.rollback()
        attempt = db.query(WompiDesembolsoSandbox).filter_by(credito_id=credito_id).with_for_update().first()
        attempt.estado = "REVISION_MANUAL"
        db.commit()
    return summary(attempt)
