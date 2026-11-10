"""Guardar tasas mensuales y condiciones aceptadas al solicitar."""
from alembic import op
import sqlalchemy as sa

revision = "12da730bf081"
down_revision = "70d5cb1a3a22"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tasas_credito_mensuales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mes", sa.String(7), nullable=False, unique=True),
        sa.Column("tasa_interes", sa.Numeric(5, 2), nullable=False),
        sa.Column("actualizada_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("actualizada_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "cotizaciones_aceptadas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("credito_id", sa.Integer(), sa.ForeignKey("creditos.id"), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("mes_tasa", sa.String(7), nullable=False),
        sa.Column("tasa_interes", sa.Numeric(5, 2), nullable=False),
        sa.Column("monto", sa.Numeric(12, 2), nullable=False),
        sa.Column("plazo_meses", sa.Integer(), nullable=False),
        sa.Column("cuota_mensual", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_estimado", sa.Numeric(12, 2), nullable=False),
        sa.Column("fecha_aceptacion", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("credito_id", name="uq_cotizacion_credito"),
    )


def downgrade():
    raise NotImplementedError("No se eliminan los registros de condiciones aceptadas.")
