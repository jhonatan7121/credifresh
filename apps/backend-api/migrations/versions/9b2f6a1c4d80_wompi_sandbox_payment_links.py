"""Add Wompi Sandbox payment link records."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b2f6a1c4d80"
down_revision: Union[str, Sequence[str], None] = "f2a91e6d04bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wompi_pagos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("credito_id", sa.Integer(), nullable=False),
        sa.Column("cuota_id", sa.Integer(), nullable=False),
        sa.Column("referencia", sa.String(length=36), nullable=False),
        sa.Column("wompi_link_id", sa.String(length=64), nullable=False),
        sa.Column("wompi_transaction_id", sa.String(length=128), nullable=True),
        sa.Column("monto_esperado", sa.Numeric(12, 2), nullable=False),
        sa.Column("estado", sa.String(length=24), nullable=False),
        sa.Column("checkout_url", sa.String(length=512), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["credito_id"], ["creditos.id"]),
        sa.ForeignKeyConstraint(["cuota_id"], ["cuotas_amortizacion.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referencia"),
        sa.UniqueConstraint("wompi_link_id"),
        sa.UniqueConstraint("wompi_transaction_id"),
    )
    op.create_index("ix_wompi_pagos_credito_id", "wompi_pagos", ["credito_id"])
    op.create_index("ix_wompi_pagos_cuota_id", "wompi_pagos", ["cuota_id"])
    op.create_index("ix_wompi_pagos_referencia", "wompi_pagos", ["referencia"])
    op.create_index("ix_wompi_pagos_wompi_link_id", "wompi_pagos", ["wompi_link_id"])
    op.create_index("ix_wompi_pagos_wompi_transaction_id", "wompi_pagos", ["wompi_transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_wompi_pagos_wompi_transaction_id", table_name="wompi_pagos")
    op.drop_index("ix_wompi_pagos_wompi_link_id", table_name="wompi_pagos")
    op.drop_index("ix_wompi_pagos_referencia", table_name="wompi_pagos")
    op.drop_index("ix_wompi_pagos_cuota_id", table_name="wompi_pagos")
    op.drop_index("ix_wompi_pagos_credito_id", table_name="wompi_pagos")
    op.drop_table("wompi_pagos")


