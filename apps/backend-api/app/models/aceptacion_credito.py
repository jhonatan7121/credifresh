from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.sql import func

from app.config.database import Base


class AceptacionCredito(Base):
    __tablename__ = "aceptaciones_credito"
    __table_args__ = (UniqueConstraint("credito_id", name="uq_aceptaciones_credito_credito_id"),)

    id = Column(Integer, primary_key=True, index=True)
    credito_id = Column(Integer, ForeignKey("creditos.id"), nullable=False)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_aceptacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    monto = Column(Numeric(12, 2), nullable=False)
    plazo_meses = Column(Integer, nullable=False)
    tasa_interes = Column(Numeric(5, 2), nullable=False)
    cuota_mensual = Column(Numeric(12, 2), nullable=False)
    total_estimado = Column(Numeric(12, 2), nullable=False)
    condiciones_version = Column(String(20), nullable=False, default="1.0")
