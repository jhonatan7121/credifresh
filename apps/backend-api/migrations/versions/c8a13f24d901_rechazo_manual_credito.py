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
    op.alter_column("evaluaciones", "tipo", server_default=None)
    op.alter_column("evaluaciones", "cuota_mensual", existing_type=sa.Numeric(12, 2), nullable=True)
    op.alter_column("evaluaciones", "capacidad_mensual", existing_type=sa.Numeric(12, 2), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE evaluaciones SET cuota_mensual = 0 WHERE cuota_mensual IS NULL")
    op.execute("UPDATE evaluaciones SET capacidad_mensual = 0 WHERE capacidad_mensual IS NULL")
    op.alter_column("evaluaciones", "cuota_mensual", existing_type=sa.Numeric(12, 2), nullable=False)
    op.alter_column("evaluaciones", "capacidad_mensual", existing_type=sa.Numeric(12, 2), nullable=False)
    op.drop_column("evaluaciones", "tipo")
