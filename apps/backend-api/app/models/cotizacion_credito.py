from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.sql import func

from app.config.database import Base


class TasaMensual(Base):
    __tablename__ = "tasas_credito_mensuales"
    id = Column(Integer, primary_key=True)
    mes = Column(String(7), nullable=False, unique=True)
    tasa_interes = Column(Numeric(5, 2), nullable=False)
    actualizada_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    actualizada_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CotizacionAceptada(Base):
    __tablename__ = "cotizaciones_aceptadas"
    __table_args__ = (UniqueConstraint("credito_id", name="uq_cotizacion_credito"),)
    id = Column(Integer, primary_key=True)
    credito_id = Column(Integer, ForeignKey("creditos.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    mes_tasa = Column(String(7), nullable=False)
    tasa_interes = Column(Numeric(5, 2), nullable=False)
    monto = Column(Numeric(12, 2), nullable=False)
    plazo_meses = Column(Integer, nullable=False)
    cuota_mensual = Column(Numeric(12, 2), nullable=False)
    total_estimado = Column(Numeric(12, 2), nullable=False)
    fecha_aceptacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
