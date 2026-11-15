"""Crear expedientes de conciliación sintética sin alterar cartera."""
from alembic import op
import sqlalchemy as sa

revision = "a91c4e17b302"
down_revision = "f16c47d390a1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("expedientes_conciliacion_sandbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("origen_id", sa.Integer(), sa.ForeignKey("expedientes_conciliacion_sandbox.id"), nullable=True),
        sa.Column("huella", sa.String(64), nullable=False, unique=True),
        sa.Column("informe_json", sa.Text(), nullable=False),
        sa.Column("resultado_json", sa.Text(), nullable=False),
        sa.Column("creador_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("creada_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("estado", sa.String(24), nullable=False))
    op.create_table("diferencias_conciliacion_sandbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("expediente_id", sa.Integer(), sa.ForeignKey("expedientes_conciliacion_sandbox.id"), nullable=False),
        sa.Column("indice", sa.Integer(), nullable=False),
        sa.Column("motivo", sa.String(80), nullable=False),
        sa.Column("transaccion_id", sa.String(128)),
        sa.Column("estado", sa.String(24), nullable=False),
        sa.Column("observacion", sa.Text()),
        sa.Column("revisor_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("revisada_en", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("expediente_id", "indice", name="uq_diferencia_expediente_indice"))
    op.create_index("ix_diferencias_conciliacion_sandbox_expediente_id", "diferencias_conciliacion_sandbox", ["expediente_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM expedientes_conciliacion_sandbox LIMIT 1")).first():
        raise RuntimeError("No se pueden eliminar expedientes de conciliación existentes.")
    op.drop_index("ix_diferencias_conciliacion_sandbox_expediente_id", table_name="diferencias_conciliacion_sandbox")
    op.drop_table("diferencias_conciliacion_sandbox")
    op.drop_table("expedientes_conciliacion_sandbox")
