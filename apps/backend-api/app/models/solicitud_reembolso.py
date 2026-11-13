from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.config.database import Base


class SolicitudReembolsoSandbox(Base):
    """Solicitud administrativa separada de la cartera y del reembolso histórico."""

    __tablename__ = "solicitudes_reembolso_sandbox"
    id = Column(Integer, primary_key=True)
    wompi_pago_id = Column(Integer, ForeignKey("wompi_pagos.id"), nullable=False, unique=True)
    pago_id = Column(Integer, ForeignKey("pagos.id"), nullable=False, unique=True)
    credito_id = Column(Integer, ForeignKey("creditos.id"), nullable=False, index=True)
    cuota_id = Column(Integer, ForeignKey("cuotas_amortizacion.id"), nullable=False)
    transaccion_id = Column(String(128), nullable=False)
    monto_centavos = Column(BigInteger, nullable=False)
    motivo = Column(String(32), nullable=False)
    descripcion = Column(Text, nullable=False)
    clasificacion = Column(String(40), nullable=False)
    evidencia = Column(String(250), nullable=False)
    solicitante_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creada_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    autorizacion = Column(String(24), nullable=False, default="PENDIENTE")
    aprobador_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    decidida_en = Column(DateTime(timezone=True), nullable=True)
    justificacion = Column(Text, nullable=True)
    version_aprobada = Column(String(64), nullable=True)
    reembolso_id = Column(Integer, ForeignKey("wompi_reembolsos_sandbox.id"), nullable=True, unique=True)
    ejecucion = Column(String(24), nullable=False, default="NO_ENVIADO")
    verificacion = Column(String(24), nullable=False, default="PENDIENTE")
    conciliacion = Column(String(24), nullable=False, default="PENDIENTE")
    revision_contable = Column(String(24), nullable=False, default="PENDIENTE")
    observacion_contable = Column(Text, nullable=True)
    cierre_usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    cerrada_en = Column(DateTime(timezone=True), nullable=True)
