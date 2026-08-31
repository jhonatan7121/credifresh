from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.config.database import Base


class Evaluacion(Base):
    __tablename__ = "evaluaciones"

    id = Column(Integer, primary_key=True, index=True)
    credito_id = Column(Integer, ForeignKey("creditos.id"), nullable=False)
    decision = Column(String, nullable=False)
    cuota_mensual = Column(Numeric(12, 2), nullable=False)
    capacidad_mensual = Column(Numeric(12, 2), nullable=False)
    motivos = Column(String, nullable=False)
    fecha_evaluacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
