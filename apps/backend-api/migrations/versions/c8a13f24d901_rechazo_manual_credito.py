"""Registrar rechazos manuales de crédito con trazabilidad.

Revision ID: c8a13f24d901
Revises: b7e21d6a4c90
Create Date: 2026-10-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8a13f24d901"
down_revision: Union[str, Sequence[str], None] = "b7e21d6a4c90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluaciones",
        sa.Column("tipo", sa.String(), nullable=False, server_default="AUTOMATICA"),
    )
    if op.get_bind().dialect.name == "sqlite":
        # SQLite cannot ALTER COLUMN directly; batch mode rebuilds the table
        # while preserving rows and constraints.
        with op.batch_alter_table("evaluaciones") as batch_op:
            batch_op.alter_column("tipo", existing_type=sa.String(), server_default=None)
            batch_op.alter_column("cuota_mensual", existing_type=sa.Numeric(12, 2), nullable=True)
            batch_op.alter_column("capacidad_mensual", existing_type=sa.Numeric(12, 2), nullable=True)
    else:
        op.alter_column("evaluaciones", "tipo", server_default=None)
        op.alter_column("evaluaciones", "cuota_mensual", existing_type=sa.Numeric(12, 2), nullable=True)
        op.alter_column("evaluaciones", "capacidad_mensual", existing_type=sa.Numeric(12, 2), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE evaluaciones SET cuota_mensual = 0 WHERE cuota_mensual IS NULL")
    op.execute("UPDATE evaluaciones SET capacidad_mensual = 0 WHERE capacidad_mensual IS NULL")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("evaluaciones") as batch_op:
            batch_op.alter_column("cuota_mensual", existing_type=sa.Numeric(12, 2), nullable=False)
            batch_op.alter_column("capacidad_mensual", existing_type=sa.Numeric(12, 2), nullable=False)
    else:
        op.alter_column("evaluaciones", "cuota_mensual", existing_type=sa.Numeric(12, 2), nullable=False)
        op.alter_column("evaluaciones", "capacidad_mensual", existing_type=sa.Numeric(12, 2), nullable=False)
    op.drop_column("evaluaciones", "tipo")
