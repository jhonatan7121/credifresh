"""Solicitudes administrativas separadas de los reembolsos existentes."""
from alembic import op
import sqlalchemy as sa

revision = "f16c47d390a1"
down_revision = "e34f8c19b621"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "solicitudes_reembolso_sandbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wompi_pago_id", sa.Integer(), sa.ForeignKey("wompi_pagos.id"), nullable=False, unique=True),
        sa.Column("pago_id", sa.Integer(), sa.ForeignKey("pagos.id"), nullable=False, unique=True),
        sa.Column("credito_id", sa.Integer(), sa.ForeignKey("creditos.id"), nullable=False),
        sa.Column("cuota_id", sa.Integer(), sa.ForeignKey("cuotas_amortizacion.id"), nullable=False),
        sa.Column("transaccion_id", sa.String(128), nullable=False),
        sa.Column("monto_centavos", sa.BigInteger(), nullable=False),
        sa.Column("motivo", sa.String(32), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("clasificacion", sa.String(40), nullable=False),
        sa.Column("evidencia", sa.String(250), nullable=False),
        sa.Column("solicitante_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("creada_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("autorizacion", sa.String(24), nullable=False),
        sa.Column("aprobador_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("decidida_en", sa.DateTime(timezone=True)),
        sa.Column("justificacion", sa.Text()),
        sa.Column("version_aprobada", sa.String(64)),
        sa.Column("reembolso_id", sa.Integer(), sa.ForeignKey("wompi_reembolsos_sandbox.id"), unique=True),
        sa.Column("ejecucion", sa.String(24), nullable=False),
        sa.Column("verificacion", sa.String(24), nullable=False),
        sa.Column("conciliacion", sa.String(24), nullable=False),
        sa.Column("revision_contable", sa.String(24), nullable=False),
        sa.Column("observacion_contable", sa.Text()),
        sa.Column("cierre_usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("cerrada_en", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_solicitudes_reembolso_sandbox_credito_id", "solicitudes_reembolso_sandbox", ["credito_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM solicitudes_reembolso_sandbox LIMIT 1")).first():
        raise RuntimeError("No se puede borrar la trazabilidad de solicitudes de reembolso.")
    op.drop_index("ix_solicitudes_reembolso_sandbox_credito_id", table_name="solicitudes_reembolso_sandbox")
    op.drop_table("solicitudes_reembolso_sandbox")
