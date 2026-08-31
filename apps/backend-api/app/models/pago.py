from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.config.database import Base


class Pago(Base):
    __tablename__ = "pagos"

    id = Column(Integer, primary_key=True, index=True)
    credito_id = Column(Integer, ForeignKey("creditos.id"), nullable=False)
    cuota_id = Column(Integer, ForeignKey("cuotas_amortizacion.id"), nullable=False)
    monto_pagado = Column(Numeric(12, 2), nullable=False)
    fecha_pago = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    metodo_pago = Column(String, nullable=False, default="TRANSFERENCIA")
