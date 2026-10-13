"""Agregar correo de contacto al cliente.

Revision ID: b7e21d6a4c90
Revises: 4ac32f7a8d19
Create Date: 2026-10-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e21d6a4c90"
down_revision: Union[str, Sequence[str], None] = "4ac32f7a8d19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clientes", sa.Column("email", sa.String(length=254), nullable=True))


def downgrade() -> None:
    op.drop_column("clientes", "email")
