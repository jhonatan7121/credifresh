from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.sql import func

from app.config.database import Base


class WompiReembolsoSandbox(Base):
    """Una sola solicitud de prueba por transacción, incluso si la respuesta se pierde."""

    __tablename__ = "wompi_reembolsos_sandbox"

    id = Column(Integer, primary_key=True)
    wompi_pago_id = Column(Integer, ForeignKey("wompi_pagos.id"), nullable=False, unique=True)
    referencia = Column(String(36), nullable=False, unique=True)
    monto = Column(Numeric(12, 2), nullable=False)
    escenario = Column(String(16), nullable=False)
    estado = Column(String(24), nullable=False)
    estado_proveedor = Column(String(24), nullable=True)
    wompi_reembolso_id = Column(String(128), nullable=True)
    creado_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actualizado_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
