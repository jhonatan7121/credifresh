from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.config.database import Base


class WompiDesembolsoSandbox(Base):
    """One durable, synthetic Sandbox attempt for each credit."""

    __tablename__ = "wompi_desembolsos_sandbox"

    id = Column(Integer, primary_key=True)
    credito_id = Column(Integer, ForeignKey("creditos.id"), nullable=False, unique=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    referencia_lote = Column(String(64), nullable=False, unique=True)
    referencia_transaccion = Column(String(64), nullable=False, unique=True)
    payout_id = Column(String(128), nullable=True, unique=True, index=True)
    monto_centavos = Column(BigInteger, nullable=False)
    estado = Column(String(32), nullable=False, default="ENVIANDO")
    creado_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actualizado_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
