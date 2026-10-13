"""Registrar aceptación de condiciones por el cliente.

Revision ID: 4ac32f7a8d19
Revises: dddbbf1eeb84
Create Date: 2026-10-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4ac32f7a8d19"
down_revision: Union[str, Sequence[str], None] = "dddbbf1eeb84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "aceptaciones_credito",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("credito_id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("fecha_aceptacion", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("monto", sa.Numeric(12, 2), nullable=False),
        sa.Column("plazo_meses", sa.Integer(), nullable=False),
        sa.Column("tasa_interes", sa.Numeric(5, 2), nullable=False),
        sa.Column("cuota_mensual", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_estimado", sa.Numeric(12, 2), nullable=False),
        sa.Column("condiciones_version", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"]),
        sa.ForeignKeyConstraint(["credito_id"], ["creditos.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credito_id", name="uq_aceptaciones_credito_credito_id"),
    )
    op.create_index(op.f("ix_aceptaciones_credito_id"), "aceptaciones_credito", ["id"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("No se elimina la tabla de aceptaciones porque contiene constancias del cliente.")
