from sqlalchemy import Column, Integer, String, Boolean
from app.config.database import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    rol = Column(String, default="CLIENTE", nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
