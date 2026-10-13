"""Añadir dirección de contacto y control de enlaces de recuperación."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e71c5a2048bf"
down_revision: Union[str, Sequence[str], None] = "c8a13f24d901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clientes", sa.Column("direccion", sa.String(length=240), nullable=True))
    op.add_column("usuarios", sa.Column("password_reset_issued_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("usuarios", sa.Column("auth_token_version", sa.Integer(), nullable=False, server_default="1"))
    op.alter_column("usuarios", "auth_token_version", server_default=None)


def downgrade() -> None:
    op.drop_column("usuarios", "password_reset_issued_at")
    op.drop_column("usuarios", "auth_token_version")
    op.drop_column("clientes", "direccion")
