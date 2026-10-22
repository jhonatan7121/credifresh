"""Add shared authentication rate-limit windows."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a91e6d04bc"
down_revision: Union[str, Sequence[str], None] = "e71c5a2048bf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_rate_limit_windows",
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.BigInteger(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("key_hash"),
    )
    op.create_index(
        "ix_auth_rate_limit_windows_updated_at",
        "auth_rate_limit_windows",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_auth_rate_limit_windows_updated_at", table_name="auth_rate_limit_windows")
    op.drop_table("auth_rate_limit_windows")
