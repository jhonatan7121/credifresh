"""Add isolated Sandbox payout attempts for credit reconciliation."""
from alembic import op
import sqlalchemy as sa

revision = "70d5cb1a3a22"
down_revision = "9b2f6a1c4d80"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wompi_desembolsos_sandbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("credito_id", sa.Integer(), sa.ForeignKey("creditos.id"), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("referencia_lote", sa.String(64), nullable=False, unique=True),
        sa.Column("referencia_transaccion", sa.String(64), nullable=False, unique=True),
        sa.Column("payout_id", sa.String(128), nullable=True),
        sa.Column("monto_centavos", sa.BigInteger(), nullable=False),
        sa.Column("estado", sa.String(32), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_wompi_desembolsos_sandbox_credito_id", "wompi_desembolsos_sandbox", ["credito_id"], unique=True)
    op.create_index("ix_wompi_desembolsos_sandbox_payout_id", "wompi_desembolsos_sandbox", ["payout_id"], unique=True)


def downgrade():
    op.drop_index("ix_wompi_desembolsos_sandbox_payout_id", table_name="wompi_desembolsos_sandbox")
    op.drop_index("ix_wompi_desembolsos_sandbox_credito_id", table_name="wompi_desembolsos_sandbox")
    op.drop_table("wompi_desembolsos_sandbox")
