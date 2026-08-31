from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.config.database import Base


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    credito_id = Column(Integer, ForeignKey("creditos.id"), nullable=True, index=True)
    titulo = Column(String, nullable=False)
    mensaje = Column(String, nullable=False)
    leida = Column(Boolean, default=False, nullable=False)
    fecha_creacion = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
