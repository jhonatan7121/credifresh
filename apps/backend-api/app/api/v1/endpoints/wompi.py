import secrets
import os
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.deps import RoleChecker, get_current_active_user
from app.models.amortizacion import CuotaAmortizacion
from app.models.audit_log import AuditLog
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.pago import Pago
from app.models.usuario import Usuario
from app.models.wompi_pago import WompiPago
from app.services.wompi_service import consultar_transaccion, crear_link_pago, get_wompi_environment, validar_firma_evento, verificar_configuracion_recaudo
from modules.audit.audit_service import registrar_auditoria


router = APIRouter(prefix="/integraciones/wompi", tags=["Wompi"])


class ReconciliacionSandbox(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def _exigir_sandbox_recaudo():
    if os.getenv("ENVIRONMENT", "").strip().lower() != "sandbox" or get_wompi_environment() != "sandbox":
        raise HTTPException(status_code=404, detail="Reconciliación disponible únicamente en Sandbox.")


@router.get("/sandbox/revision-enlaces")
def listar_enlaces_por_revisar(
    db: Session = Depends(get_db), current_user: Usuario = Depends(RoleChecker(["ADMIN"]))
):
    """List unresolved reservations without exposing checkout URLs or secrets."""
    _exigir_sandbox_recaudo()
    attempts = (db.query(WompiPago).filter(WompiPago.estado.in_(["CREANDO", "INCIERTO"]))
                .order_by(WompiPago.id.asc()).limit(100).all())
    return {"intentos": [{"credito_id": row.credito_id, "cuota_id": row.cuota_id,
                         "referencia": row.referencia, "estado": row.estado,
                         "creado_en": row.creado_en.isoformat() if row.creado_en else None}
                        for row in attempts]}


@router.post("/sandbox/creditos/{credito_id}/cuotas/{cuota_id}/reconciliar")
def reconciliar_cuota_sandbox(
    credito_id: int, cuota_id: int, datos: ReconciliacionSandbox,
    db: Session = Depends(get_db), current_user: Usuario = Depends(RoleChecker(["ADMIN"]))
):
    """Recover a specific known transaction without trusting client-provided status or amounts."""
    _exigir_sandbox_recaudo()
    transaction = consultar_transaccion(datos.transaction_id)
    link_id = transaction.get("payment_link_id")
    if not isinstance(link_id, str) or not link_id:
        raise HTTPException(status_code=502, detail="Wompi no confirmó el link asociado a la transacción.")
    intento = db.query(WompiPago).filter_by(credito_id=credito_id, cuota_id=cuota_id, wompi_link_id=link_id).first()
    if not intento:
        raise HTTPException(status_code=409, detail="La transacción no corresponde al link registrado para esta cuota.")
    return _aplicar_transaccion_verificada(db, transaction, "sandbox", actor=current_user)


@router.get("/sandbox/creditos/{credito_id}/cuotas/{cuota_id}/comparar")
def comparar_cuota_sandbox(
    credito_id: int, cuota_id: int,
    db: Session = Depends(get_db), current_user: Usuario = Depends(RoleChecker(["ADMIN"]))
):
    """Compare a recorded attempt with Wompi; never change the ledger or infer bank settlement."""
    _exigir_sandbox_recaudo()
    cuota = db.query(CuotaAmortizacion).filter_by(id=cuota_id, credito_id=credito_id).first()
    if not cuota:
        raise HTTPException(status_code=404, detail="Crédito o cuota no encontrados.")
    intento = (db.query(WompiPago).filter_by(credito_id=credito_id, cuota_id=cuota_id)
               .order_by(WompiPago.id.desc()).first())
    pagos = db.query(Pago).filter_by(credito_id=credito_id, cuota_id=cuota_id, metodo_pago="WOMPI_SANDBOX").all()
    total = sum((Decimal(str(pago.monto_pagado)) for pago in pagos), Decimal("0"))
    result = {
        "credito_id": credito_id, "cuota_id": cuota_id, "estado_cuota": cuota.estado,
        "monto_cuota": str(cuota.monto_cuota), "monto_pagado_cuota": str(cuota.monto_pagado),
        "pagos_wompi_registrados": len(pagos), "total_pagos_wompi": str(total),
        "estado_intento": intento.estado if intento else None,
        "estado_wompi": None, "resultado": "REQUIERE_REVISION",
        "motivos": [], "abono_bancario_verificado": False, "reembolsos_verificados": False,
    }
    if not intento or not intento.wompi_transaction_id:
        result["motivos"].append("SIN_TRANSACCION_REGISTRADA_EN_CREDIFRESH")
        return result
    transaccion = consultar_transaccion(intento.wompi_transaction_id)
    result["estado_wompi"] = transaccion.get("status")
    if transaccion.get("payment_link_id") != intento.wompi_link_id:
        result["motivos"].append("ENLACE_NO_COINCIDE")
    cents = transaccion.get("amount_in_cents")
    expected = int((Decimal(str(intento.monto_esperado)) * 100).quantize(Decimal("1")))
    if type(cents) is not int or cents != expected or transaccion.get("currency") != "COP":
        result["motivos"].append("MONTO_O_MONEDA_NO_COINCIDE")
    if transaccion.get("status") != "APPROVED" or intento.estado != "PAGADO":
        result["motivos"].append("ESTADO_NO_CONFIRMADO_O_CAMBIO_DE_ESTADO")
    if len(pagos) != 1 or total != Decimal(str(intento.monto_esperado)):
        result["motivos"].append("PAGOS_LOCALES_NO_COINCIDEN")
    if (cuota.estado != "PAGADA" or Decimal(str(cuota.monto_pagado)) != total or
            Decimal(str(cuota.monto_cuota)) != Decimal(str(intento.monto_esperado))):
        result["motivos"].append("SALDO_CUOTA_NO_COINCIDE_CON_PAGOS_WOMPI")
    if not result["motivos"]:
        result["resultado"] = "COINCIDE_RECAUDO_NO_CONCILIACION_BANCARIA"
    return result


@router.post("/creditos/{credito_id}/cuotas/{cuota_id}/link", status_code=201)
def crear_link_para_cuota(
    credito_id: int,
    cuota_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user),
):
    credito = db.query(Credito).filter(Credito.id == credito_id).first()
    cuota = db.query(CuotaAmortizacion).filter(
        CuotaAmortizacion.id == cuota_id,
        CuotaAmortizacion.credito_id == credito_id,
    ).with_for_update().first()
    if not credito or not cuota:
        raise HTTPException(status_code=404, detail="Crédito o cuota no encontrados.")
    if credito.estado != "DESEMBOLSADO":
        raise HTTPException(status_code=409, detail="Solo se pueden cobrar cuotas de créditos desembolsados.")
    if current_user.rol == "CLIENTE":
        cliente = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
        if not cliente or cliente.id != credito.cliente_id:
            raise HTTPException(status_code=403, detail="No tienes permiso para pagar este crédito.")
    elif current_user.rol not in {"ADMIN", "GESTOR"}:
        raise HTTPException(status_code=403, detail="No tienes permiso para crear links de pago.")

    verificar_configuracion_recaudo()
    pendiente = Decimal(str(cuota.monto_cuota)) - Decimal(str(cuota.monto_pagado))
    if pendiente <= 0:
        raise HTTPException(status_code=409, detail="La cuota ya está pagada.")
    existente = (
        db.query(WompiPago)
        .filter(
            WompiPago.cuota_id == cuota.id,
            WompiPago.estado.in_(["CREANDO", "INCIERTO", "PENDIENTE", "FALLIDO"]),
        )
        .order_by(WompiPago.id.desc())
        .first()
    )
    if existente:
        if not existente.wompi_link_id or not existente.checkout_url:
            raise HTTPException(status_code=409, detail="La creación del link requiere revisión; no se generará otro automáticamente.")
        if Decimal(str(existente.monto_esperado)) != pendiente:
            raise HTTPException(status_code=409, detail="El saldo cambió desde la creación del link; se requiere revisión.")
        return {
            "referencia": existente.referencia,
            "credito_id": credito.id,
            "cuota_id": cuota.id,
            "monto_cop": str(existente.monto_esperado),
            "estado": existente.estado,
            "checkout_url": existente.checkout_url,
            "ambiente": get_wompi_environment(),
        }

    referencia = secrets.token_hex(16)
    numero_cuota = cuota.numero_cuota
    intento = WompiPago(
        credito_id=credito.id,
        cuota_id=cuota.id,
        referencia=referencia,
        wompi_link_id=None,
        monto_esperado=pendiente,
        estado="CREANDO",
        checkout_url=None,
    )
    db.add(intento)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un intento de pago para esta cuota; vuelve a consultar.") from exc
    # The committed reservation survives a timeout or process crash, preventing
    # an automatic second link even when Wompi's response was lost.
    try:
        link = crear_link_pago(referencia=referencia, credito_id=credito_id, numero_cuota=numero_cuota, monto=pendiente)
    except Exception:
        intento.estado = "INCIERTO"
        db.commit()
        raise HTTPException(status_code=503, detail="No se confirmó la creación del link. Se requiere revisión antes de otro intento.")
    intento.wompi_link_id = link["id"]
    intento.checkout_url = link["checkout_url"]
    intento.estado = "PENDIENTE"
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="No se pudo confirmar el link creado. Se requiere revisión.") from exc
    return {
        "referencia": referencia,
        "credito_id": credito.id,
        "cuota_id": cuota.id,
        "monto_cop": str(pendiente),
        "estado": intento.estado,
        "checkout_url": intento.checkout_url,
        "ambiente": link["ambiente"],
    }


@router.get("/creditos/{credito_id}/cuotas/{cuota_id}/estado")
def obtener_estado_intento_cuota(
    credito_id: int,
    cuota_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user),
):
    """Return the latest Wompi Sandbox attempt without exposing its checkout URL."""
    credito = db.query(Credito).filter(Credito.id == credito_id).first()
    cuota = db.query(CuotaAmortizacion).filter(
        CuotaAmortizacion.id == cuota_id,
        CuotaAmortizacion.credito_id == credito_id,
    ).first()
    if not credito or not cuota:
        raise HTTPException(status_code=404, detail="Crédito o cuota no encontrados.")
    if current_user.rol == "CLIENTE":
        cliente = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
        if not cliente or cliente.id != credito.cliente_id:
            raise HTTPException(status_code=403, detail="No tienes permiso para consultar este crédito.")
    elif current_user.rol not in {"ADMIN", "GESTOR"}:
        raise HTTPException(status_code=403, detail="No tienes permiso para consultar este intento.")

    intento = (
        db.query(WompiPago)
        .filter(WompiPago.cuota_id == cuota.id)
        .order_by(WompiPago.id.desc())
        .first()
    )
    return {
        "credito_id": credito.id,
        "cuota_id": cuota.id,
        "estado_cuota": cuota.estado,
        "monto_cuota": str(cuota.monto_cuota),
        "monto_pagado": str(cuota.monto_pagado),
        "estado_ultimo_intento": intento.estado if intento else None,
        "actualizado_en": intento.actualizado_en.isoformat() if intento and intento.actualizado_en else None,
    }


async def _recibir_evento(
    request: Request,
    db: Session = Depends(get_db),
    x_event_checksum: str | None = Header(default=None, alias="X-Event-Checksum"),
    expected_environment: str = "sandbox",
):
    try:
        event = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="El evento recibido no contiene JSON válido.") from exc
    configured_environment = get_wompi_environment()
    expected_event_environment = "test" if expected_environment == "sandbox" else "prod"
    if configured_environment != expected_environment:
        raise HTTPException(status_code=404, detail="El endpoint no está habilitado para el ambiente configurado.")
    if not isinstance(event, dict) or event.get("environment") != expected_event_environment:
        raise HTTPException(status_code=400, detail="El ambiente del evento no coincide con este endpoint.")
    if not validar_firma_evento(event, x_event_checksum):
        raise HTTPException(status_code=401, detail="La firma del evento de Wompi no es válida.")
    if event.get("event") != "transaction.updated":
        return {"recibido": True, "procesado": False}

    event_transaction = (event.get("data") or {}).get("transaction") or {}
    transaction_id = event_transaction.get("id") if isinstance(event_transaction, dict) else None
    if not isinstance(transaction_id, str) or not transaction_id:
        raise HTTPException(status_code=400, detail="El evento no identifica la transacción.")
    if "transaction.id" not in event["signature"]["properties"]:
        raise HTTPException(status_code=401, detail="La firma no protege el identificador de la transacción.")
    # Fields absent from signature.properties must not determine the ledger.
    # Wompi is the authority for link, currency, amount, and current status.
    transaction = await run_in_threadpool(consultar_transaccion, transaction_id)
    return _aplicar_transaccion_verificada(db, transaction, expected_environment)


def _aplicar_transaccion_verificada(db: Session, transaction: dict, expected_environment: str, actor: Usuario | None = None):
    transaction_id = transaction.get("id")
    if not isinstance(transaction_id, str) or not transaction_id:
        raise HTTPException(status_code=502, detail="Wompi no confirmó el identificador de la transacción.")
    link_id = transaction.get("payment_link_id")
    if not isinstance(link_id, str) or not link_id:
        raise HTTPException(status_code=502, detail="Wompi no confirmó el link asociado a la transacción.")

    existing = db.query(WompiPago).filter(WompiPago.wompi_transaction_id == transaction_id).with_for_update().first()
    if existing:
        estado = transaction.get("status")
        consistent = ((existing.estado == "PAGADO" and estado == "APPROVED") or
                      (existing.estado == "FALLIDO" and estado in {"DECLINED", "ERROR", "VOIDED"}))
        if transaction.get("payment_link_id") != existing.wompi_link_id:
            raise HTTPException(status_code=409, detail="El link de la transacción cambió; requiere revisión.")
        if not consistent:
            action = "ALERTA_CAMBIO_ESTADO_WOMPI"
            already_alerted = db.query(AuditLog).filter_by(
                accion=action, entidad="wompi_pago", entidad_id=existing.id, resultado="REQUIERE_REVISION"
            ).first()
            if not already_alerted:
                registrar_auditoria(db=db, usuario=actor, accion=action, entidad="wompi_pago",
                    entidad_id=existing.id, resultado="REQUIERE_REVISION",
                    detalles={"credito_id": existing.credito_id, "cuota_id": existing.cuota_id,
                              "estado_local": existing.estado, "estado_wompi": estado})
                db.commit()
            return {"recibido": True, "procesado": False, "requiere_revision": True}
        return {"recibido": True, "procesado": True, "duplicado": True}

    intento = db.query(WompiPago).filter(WompiPago.wompi_link_id == link_id).with_for_update().first()
    if not intento:
        return {"recibido": True, "procesado": False}
    if intento.estado == "PAGADO":
        return {"recibido": True, "procesado": False, "requiere_revision": True}

    estado = transaction.get("status")
    if estado != "APPROVED":
        estado_final_fallido = estado in {"DECLINED", "ERROR", "VOIDED"}
        intento.estado = "FALLIDO" if estado_final_fallido else "PENDIENTE"
        # Wompi can send transaction.updated more than once for the same
        # transaction (for example PENDING followed by APPROVED). Only mark
        # an ID as handled once its status is terminal, so a later approval
        # is not mistaken for a duplicate of an earlier pending notification.
        if estado_final_fallido:
            intento.wompi_transaction_id = transaction_id
        if actor:
            registrar_auditoria(db=db, usuario=actor, accion="RECONCILIAR_CUOTA_WOMPI_SANDBOX",
                entidad="credito", entidad_id=intento.credito_id,
                detalles={"cuota_id": intento.cuota_id, "estado_wompi": estado})
        db.commit()
        return {"recibido": True, "procesado": False, "estado": intento.estado}

    amount = transaction.get("amount_in_cents")
    if transaction.get("currency") != "COP" or not isinstance(amount, int):
        raise HTTPException(status_code=400, detail="El evento aprobado no tiene monto o moneda válidos.")
    expected_cents = int((Decimal(str(intento.monto_esperado)) * 100).quantize(Decimal("1")))
    if amount != expected_cents:
        raise HTTPException(status_code=409, detail="El monto del evento no coincide con el link registrado.")

    credito = db.query(Credito).filter(Credito.id == intento.credito_id).with_for_update().first()
    cuota = db.query(CuotaAmortizacion).filter(CuotaAmortizacion.id == intento.cuota_id).with_for_update().first()
    if not credito or not cuota or credito.estado != "DESEMBOLSADO":
        raise HTTPException(status_code=409, detail="El crédito ya no admite la aplicación de este pago.")
    pendiente = Decimal(str(cuota.monto_cuota)) - Decimal(str(cuota.monto_pagado))
    monto_pagado = Decimal(amount) / Decimal(100)
    if monto_pagado != pendiente:
        raise HTTPException(status_code=409, detail="El saldo de la cuota cambió; el pago requiere revisión manual.")

    cuota.monto_pagado = Decimal(str(cuota.monto_pagado)) + monto_pagado
    cuota.estado = "PAGADA" if cuota.monto_pagado >= Decimal(str(cuota.monto_cuota)) else "PAGO_PARCIAL"
    db.add(Pago(
        credito_id=credito.id,
        cuota_id=cuota.id,
        monto_pagado=monto_pagado,
        metodo_pago="WOMPI_SANDBOX" if expected_environment == "sandbox" else "WOMPI",
    ))
    intento.estado = "PAGADO"
    intento.wompi_transaction_id = transaction_id
    cuotas = db.query(CuotaAmortizacion).filter(CuotaAmortizacion.credito_id == credito.id).all()
    if cuotas and all(item.estado == "PAGADA" or item.id == cuota.id for item in cuotas):
        credito.estado = "PAGADO"
    if actor:
        registrar_auditoria(db=db, usuario=actor, accion="RECONCILIAR_CUOTA_WOMPI_SANDBOX",
            entidad="credito", entidad_id=intento.credito_id,
            detalles={"cuota_id": intento.cuota_id, "estado_wompi": estado})
    db.commit()
    return {"recibido": True, "procesado": True, "estado": "PAGADO"}


@router.post("/sandbox/eventos", status_code=200)
async def recibir_evento_sandbox(
    request: Request,
    db: Session = Depends(get_db),
    x_event_checksum: str | None = Header(default=None, alias="X-Event-Checksum"),
):
    return await _recibir_evento(request, db, x_event_checksum, "sandbox")


@router.post("/production/eventos", status_code=200)
async def recibir_evento_produccion(
    request: Request,
    db: Session = Depends(get_db),
    x_event_checksum: str | None = Header(default=None, alias="X-Event-Checksum"),
):
    return await _recibir_evento(request, db, x_event_checksum, "production")
