import datetime
from decimal import Decimal
from typing import Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.amortizacion import CuotaAmortizacion
from app.models.pago import Pago as PagoModel
from app.models.aceptacion_credito import AceptacionCredito


COLOMBIA_TZ = datetime.timezone(datetime.timedelta(hours=-5))


def calcular_resumen_cartera(db: Session) -> Dict[str, Any]:
    """Calcula las métricas de resumen ejecutivo de la cartera con precisión Decimal."""
    total_clientes = db.query(func.count(Cliente.id)).scalar() or 0

    # Conteos por estado de crédito
    estados = ["SOLICITADO", "APROBADO", "RECHAZADO", "DESEMBOLSADO", "PAGADO"]
    conteos_creditos = {}
    for est in estados:
        cnt = db.query(func.count(Credito.id)).filter(Credito.estado == est).scalar() or 0
        conteos_creditos[est.lower()] = cnt

    total_creditos = sum(conteos_creditos.values())

    # Montos totales
    monto_total_solicitado_raw = db.query(func.sum(Credito.monto)).scalar()
    monto_total_solicitado = Decimal(str(monto_total_solicitado_raw)) if monto_total_solicitado_raw is not None else Decimal("0.00")

    # Monto total desembolsado (créditos en estado DESEMBOLSADO o PAGADO)
    monto_desembolsado_raw = (
        db.query(func.sum(Credito.monto))
        .filter(Credito.estado.in_(["DESEMBOLSADO", "PAGADO"]))
        .scalar()
    )
    monto_total_desembolsado = Decimal(str(monto_desembolsado_raw)) if monto_desembolsado_raw is not None else Decimal("0.00")

    # Monto total recaudado por pagos
    recaudo_raw = db.query(func.sum(PagoModel.monto_pagado)).scalar()
    monto_total_recaudado = Decimal(str(recaudo_raw)) if recaudo_raw is not None else Decimal("0.00")

    aceptados_sin_desembolso = (
        db.query(
            func.count(AceptacionCredito.credito_id),
            func.coalesce(func.sum(AceptacionCredito.monto), 0),
        )
        .join(Credito, Credito.id == AceptacionCredito.credito_id)
        .filter(Credito.estado == "APROBADO")
        .one()
    )
    creditos_aceptados_sin_desembolso = aceptados_sin_desembolso[0] or 0
    monto_aceptado_sin_desembolso = Decimal(str(aceptados_sin_desembolso[1] or 0))

    return {
        "total_clientes": total_clientes,
        "total_creditos": total_creditos,
        "creditos_por_estado": conteos_creditos,
        "monto_total_solicitado": monto_total_solicitado.quantize(Decimal("0.01")),
        "monto_total_desembolsado": monto_total_desembolsado.quantize(Decimal("0.01")),
        "monto_total_recaudado": monto_total_recaudado.quantize(Decimal("0.01")),
        "creditos_aceptados_sin_desembolso": creditos_aceptados_sin_desembolso,
        "monto_aceptado_sin_desembolso": monto_aceptado_sin_desembolso.quantize(Decimal("0.01")),
    }


def calcular_cartera_detalle(db: Session) -> Dict[str, Any]:
    """Calcula el estado detallado de la cartera (cuotas pendientes, parciales, etc.) con precisión Decimal."""
    # Estado de cuotas de amortización
    estados_cuotas = ["PENDIENTE", "PAGO_PARCIAL", "PAGADA"]
    cuotas_por_estado = {}
    for est in estados_cuotas:
        cnt = db.query(func.count(CuotaAmortizacion.id)).filter(CuotaAmortizacion.estado == est).scalar() or 0
        cuotas_por_estado[est.lower()] = cnt

    # Saldo pendiente total de cuotas (monto_cuota - monto_pagado para no pagadas)
    cuotas_activas = (
        db.query(CuotaAmortizacion)
        .filter(CuotaAmortizacion.estado.in_(["PENDIENTE", "PAGO_PARCIAL"]))
        .all()
    )

    saldo_pendiente_cartera = Decimal("0.00")
    saldo_vencido = Decimal("0.00")
    cuotas_vencidas = 0
    ahora_colombia = datetime.datetime.now(COLOMBIA_TZ)
    for c in cuotas_activas:
        m_cuota = Decimal(str(c.monto_cuota)) if c.monto_cuota is not None else Decimal("0.00")
        m_pagado = Decimal(str(c.monto_pagado)) if c.monto_pagado is not None else Decimal("0.00")
        saldo_cuota = m_cuota - m_pagado
        saldo_pendiente_cartera += saldo_cuota
        fecha_vencimiento = c.fecha_vencimiento
        if fecha_vencimiento.tzinfo is None:
            # SQLite no conserva el tzinfo de las columnas DateTime(timezone=True);
            # las fechas del plan se generan en UTC.
            fecha_vencimiento = fecha_vencimiento.replace(tzinfo=datetime.timezone.utc)
        fecha_vencimiento = fecha_vencimiento.astimezone(COLOMBIA_TZ)
        if fecha_vencimiento.date() < ahora_colombia.date():
            cuotas_vencidas += 1
            saldo_vencido += saldo_cuota

    return {
        "cuotas_por_estado": cuotas_por_estado,
        "saldo_pendiente_cartera": saldo_pendiente_cartera.quantize(Decimal("0.01")),
        "cuotas_vencidas": cuotas_vencidas,
        "saldo_vencido": saldo_vencido.quantize(Decimal("0.01")),
    }


def listar_cuotas_vencidas(db: Session, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
    """Lista cuotas pendientes de créditos desembolsados con vencimiento anterior al día local."""
    hoy_colombia = datetime.datetime.now(COLOMBIA_TZ).date()
    inicio_hoy_colombia = datetime.datetime.combine(
        hoy_colombia,
        datetime.time.min,
        tzinfo=COLOMBIA_TZ,
    ).astimezone(datetime.timezone.utc)
    consulta = (
        db.query(CuotaAmortizacion, Credito, Cliente)
        .join(Credito, Credito.id == CuotaAmortizacion.credito_id)
        .join(Cliente, Cliente.id == Credito.cliente_id)
        .filter(
            Credito.estado == "DESEMBOLSADO",
            CuotaAmortizacion.estado.in_(["PENDIENTE", "PAGO_PARCIAL"]),
            CuotaAmortizacion.monto_pagado < CuotaAmortizacion.monto_cuota,
            CuotaAmortizacion.fecha_vencimiento < inicio_hoy_colombia,
        )
    )
    total = consulta.count()
    filas = (
        consulta
        .order_by(CuotaAmortizacion.fecha_vencimiento.asc(), CuotaAmortizacion.credito_id.asc(), CuotaAmortizacion.numero_cuota.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    resultados = []
    for cuota, credito, cliente in filas:
        vencimiento = cuota.fecha_vencimiento
        if vencimiento.tzinfo is None:
            vencimiento = vencimiento.replace(tzinfo=datetime.timezone.utc)
        vencimiento = vencimiento.astimezone(COLOMBIA_TZ)
        dias_vencida = (hoy_colombia - vencimiento.date()).days
        if dias_vencida <= 0:
            continue
        saldo = Decimal(str(cuota.monto_cuota)) - Decimal(str(cuota.monto_pagado))
        resultados.append({
            "cliente_id": cliente.id,
            "cliente_nombre": cliente.nombre,
            "credito_id": credito.id,
            "cuota_id": cuota.id,
            "numero_cuota": cuota.numero_cuota,
            "fecha_vencimiento": vencimiento,
            "dias_vencida": dias_vencida,
            "saldo_pendiente": saldo.quantize(Decimal("0.01")),
        })
    return {"items": resultados, "total": total, "limit": limit, "offset": offset}
