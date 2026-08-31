from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.config.database import Base


class Credito(Base):
    __tablename__ = "creditos"

    id = Column(Integer, primary_key=True, index=True)

    cliente_id = Column(
        Integer,
        ForeignKey("clientes.id"),
        nullable=False
    )

    monto = Column(
        Numeric(12, 2),
        nullable=False
    )

    plazo_meses = Column(
        Integer,
        nullable=False
    )

    tasa_interes = Column(
        Numeric(5, 2),
        nullable=False
    )

    estado = Column(
        String,
        nullable=False,
        default="SOLICITADO"
    )

    fecha_creacion = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    fecha_evaluacion = Column(
        DateTime(timezone=True),
        nullable=True
    )
