from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.config.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    rol = Column(String, nullable=False, default="SISTEMA")
    accion = Column(String, nullable=False)
    entidad = Column(String, nullable=False)
    entidad_id = Column(Integer, nullable=True)
    resultado = Column(String, nullable=False, default="EXITOSO")
    detalles = Column(Text, nullable=True)
    ip = Column(String, nullable=True)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
