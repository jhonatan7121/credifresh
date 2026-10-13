from sqlalchemy import Column, Integer, String, ForeignKey
from app.config.database import Base


class Cliente(Base):
    __tablename__ = "clientes"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    cedula = Column(String, unique=True, nullable=False)
    telefono = Column(String, nullable=False)
    direccion = Column(String(240), nullable=True)
    email = Column(String(254), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), unique=True, nullable=True)
