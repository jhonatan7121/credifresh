from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, DateTime
from app.config.database import Base


class CuotaAmortizacion(Base):
    __tablename__ = "cuotas_amortizacion"

    id = Column(Integer, primary_key=True, index=True)
    credito_id = Column(Integer, ForeignKey("creditos.id"), nullable=False)
    numero_cuota = Column(Integer, nullable=False)
    fecha_vencimiento = Column(DateTime(timezone=True), nullable=False)
    monto_cuota = Column(Numeric(12, 2), nullable=False)
    capital = Column(Numeric(12, 2), nullable=False)
    interes = Column(Numeric(12, 2), nullable=False)
    saldo_remanente = Column(Numeric(12, 2), nullable=False)
    monto_pagado = Column(Numeric(12, 2), nullable=False, default=0.00)
    estado = Column(String, nullable=False, default="PENDIENTE")
