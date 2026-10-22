from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.sql import func

from app.config.database import Base


class WompiPago(Base):
    """Intento de cobro de una cuota mediante un link de Wompi Sandbox."""

    __tablename__ = "wompi_pagos"

    id = Column(Integer, primary_key=True, index=True)
    credito_id = Column(Integer, ForeignKey("creditos.id"), nullable=False, index=True)
    cuota_id = Column(Integer, ForeignKey("cuotas_amortizacion.id"), nullable=False, index=True)
    referencia = Column(String(36), nullable=False, unique=True, index=True)
    wompi_link_id = Column(String(64), nullable=False, unique=True, index=True)
    wompi_transaction_id = Column(String(128), nullable=True, unique=True, index=True)
    monto_esperado = Column(Numeric(12, 2), nullable=False)
    estado = Column(String(24), nullable=False, default="PENDIENTE")
    checkout_url = Column(String(512), nullable=False)
    creado_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actualizado_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
