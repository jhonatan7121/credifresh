from decimal import Decimal
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.amortizacion import CuotaAmortizacion
from app.models.pago import Pago as PagoModel


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

    return {
        "total_clientes": total_clientes,
        "total_creditos": total_creditos,
        "creditos_por_estado": conteos_creditos,
        "monto_total_solicitado": monto_total_solicitado.quantize(Decimal("0.01")),
        "monto_total_desembolsado": monto_total_desembolsado.quantize(Decimal("0.01")),
        "monto_total_recaudado": monto_total_recaudado.quantize(Decimal("0.01"))
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
    for c in cuotas_activas:
        m_cuota = Decimal(str(c.monto_cuota)) if c.monto_cuota is not None else Decimal("0.00")
        m_pagado = Decimal(str(c.monto_pagado)) if c.monto_pagado is not None else Decimal("0.00")
        saldo_pendiente_cartera += (m_cuota - m_pagado)

    return {
        "cuotas_por_estado": cuotas_por_estado,
        "saldo_pendiente_cartera": saldo_pendiente_cartera.quantize(Decimal("0.01"))
    }
