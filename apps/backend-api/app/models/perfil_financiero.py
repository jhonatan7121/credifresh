from sqlalchemy import Column, Integer, String, Numeric, ForeignKey
from app.config.database import Base


class PerfilFinanciero(Base):
    __tablename__ = "perfiles_financieros"

    id = Column(Integer, primary_key=True, index=True)

    cliente_id = Column(
        Integer,
        ForeignKey("clientes.id"),
        unique=True,
        nullable=False
    )

    ingresos_mensuales = Column(
        Numeric(12, 2),
        nullable=False
    )

    gastos_mensuales = Column(
        Numeric(12, 2),
        nullable=False
    )

    otras_obligaciones = Column(
        Numeric(12, 2),
        nullable=False,
        default=0
    )

    tipo_ingresos = Column(
        String,
        nullable=False
    )

    actividad_economica = Column(
        String,
        nullable=False
    )