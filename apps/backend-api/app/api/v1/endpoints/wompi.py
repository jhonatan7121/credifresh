import secrets
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.deps import get_current_active_user
from app.models.amortizacion import CuotaAmortizacion
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.pago import Pago
from app.models.usuario import Usuario
from app.models.wompi_pago import WompiPago
from app.services.wompi_service import crear_link_pago, validar_firma_evento


router = APIRouter(prefix="/integraciones/wompi", tags=["Wompi Sandbox"])


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
    ).first()
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

    pendiente = Decimal(str(cuota.monto_cuota)) - Decimal(str(cuota.monto_pagado))
    if pendiente <= 0:
        raise HTTPException(status_code=409, detail="La cuota ya está pagada.")
    existente = (
        db.query(WompiPago)
        .filter(
            WompiPago.cuota_id == cuota.id,
            WompiPago.estado == "PENDIENTE",
        )
        .order_by(WompiPago.id.desc())
        .first()
    )
    if existente:
        return {
            "referencia": existente.referencia,
            "credito_id": credito.id,
            "cuota_id": cuota.id,
            "monto_cop": str(existente.monto_esperado),
            "estado": existente.estado,
            "checkout_url": existente.checkout_url,
            "ambiente": "sandbox",
        }

    referencia = secrets.token_hex(16)
    link = crear_link_pago(
        referencia=referencia,
        credito_id=credito.id,
        numero_cuota=cuota.numero_cuota,
        monto=pendiente,
    )
    intento = WompiPago(
        credito_id=credito.id,
        cuota_id=cuota.id,
        referencia=referencia,
        wompi_link_id=link["id"],
        monto_esperado=pendiente,
        estado="PENDIENTE",
        checkout_url=link["checkout_url"],
    )
    db.add(intento)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="No se pudo guardar el link de pago generado.") from exc
    return {
        "referencia": referencia,
        "credito_id": credito.id,
        "cuota_id": cuota.id,
        "monto_cop": str(pendiente),
        "estado": intento.estado,
        "checkout_url": intento.checkout_url,
        "ambiente": "sandbox",
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


@router.post("/sandbox/eventos", status_code=200)
async def recibir_evento_sandbox(
    request: Request,
    db: Session = Depends(get_db),
    x_event_checksum: str | None = Header(default=None, alias="X-Event-Checksum"),
):
    try:
        event = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="El evento recibido no contiene JSON válido.") from exc
    if not isinstance(event, dict) or event.get("environment") != "test":
        raise HTTPException(status_code=400, detail="Este endpoint solo acepta eventos de Sandbox.")
    if not validar_firma_evento(event, x_event_checksum):
        raise HTTPException(status_code=401, detail="La firma del evento de Wompi no es válida.")
    if event.get("event") != "transaction.updated":
        return {"recibido": True, "procesado": False}

    transaction = (event.get("data") or {}).get("transaction") or {}
    transaction_id = transaction.get("id")
    link_id = transaction.get("payment_link_id")
    if not isinstance(transaction_id, str) or not transaction_id or not isinstance(link_id, str) or not link_id:
        raise HTTPException(status_code=400, detail="El evento no identifica la transacción y el link de pago.")

    existing = db.query(WompiPago).filter(WompiPago.wompi_transaction_id == transaction_id).first()
    if existing:
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
        metodo_pago="WOMPI_SANDBOX",
    ))
    intento.estado = "PAGADO"
    intento.wompi_transaction_id = transaction_id
    cuotas = db.query(CuotaAmortizacion).filter(CuotaAmortizacion.credito_id == credito.id).all()
    if cuotas and all(item.estado == "PAGADA" or item.id == cuota.id for item in cuotas):
        credito.estado = "PAGADO"
    db.commit()
    return {"recibido": True, "procesado": True, "estado": "PAGADO"}
