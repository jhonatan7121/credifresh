"""Registrar una única solicitud de reembolso de prueba por pago Wompi."""

from alembic import op
import sqlalchemy as sa

revision = "e34f8c19b621"
down_revision = "c6130a57e241"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wompi_reembolsos_sandbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wompi_pago_id", sa.Integer(), sa.ForeignKey("wompi_pagos.id"), nullable=False, unique=True),
        sa.Column("referencia", sa.String(36), nullable=False, unique=True),
        sa.Column("monto", sa.Numeric(12, 2), nullable=False),
        sa.Column("escenario", sa.String(16), nullable=False),
        sa.Column("estado", sa.String(24), nullable=False),
        sa.Column("estado_proveedor", sa.String(24), nullable=True),
        sa.Column("wompi_reembolso_id", sa.String(128), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM wompi_reembolsos_sandbox LIMIT 1")).first():
        raise RuntimeError("Hay reembolsos de prueba registrados; no se puede perder su trazabilidad.")
    op.drop_table("wompi_reembolsos_sandbox")
