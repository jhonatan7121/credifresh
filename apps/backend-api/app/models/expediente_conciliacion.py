"""Expedientes de conciliación de prueba; nunca representan un cierre bancario."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func
from app.config.database import Base


class ExpedienteConciliacionSandbox(Base):
    __tablename__ = "expedientes_conciliacion_sandbox"
    id = Column(Integer, primary_key=True)
    origen_id = Column(Integer, ForeignKey("expedientes_conciliacion_sandbox.id"), nullable=True)
    huella = Column(String(64), nullable=False, unique=True)
    informe_json = Column(Text, nullable=False)
    resultado_json = Column(Text, nullable=False)
    creador_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creada_en = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    estado = Column(String(24), nullable=False, default="REQUIERE_REVISION")


class DiferenciaConciliacionSandbox(Base):
    __tablename__ = "diferencias_conciliacion_sandbox"
    __table_args__ = (UniqueConstraint("expediente_id", "indice", name="uq_diferencia_expediente_indice"),)
    id = Column(Integer, primary_key=True)
    expediente_id = Column(Integer, ForeignKey("expedientes_conciliacion_sandbox.id"), nullable=False, index=True)
    indice = Column(Integer, nullable=False)
    motivo = Column(String(80), nullable=False)
    transaccion_id = Column(String(128), nullable=True)
    estado = Column(String(24), nullable=False, default="ABIERTA")
    observacion = Column(Text, nullable=True)
    revisor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    revisada_en = Column(DateTime(timezone=True), nullable=True)
