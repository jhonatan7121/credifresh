"""Reserve an installment before requesting its Wompi payment link."""

from alembic import op
import sqlalchemy as sa

revision = "c6130a57e241"
down_revision = "12da730bf081"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    duplicate = connection.execute(sa.text("""
        SELECT cuota_id FROM wompi_pagos
        WHERE estado IN ('CREANDO', 'INCIERTO', 'PENDIENTE', 'FALLIDO')
        GROUP BY cuota_id HAVING COUNT(*) > 1 LIMIT 1
    """)).first()
    if duplicate:
        raise RuntimeError("Hay múltiples intentos abiertos para una cuota; reconciliarlos antes de migrar.")
    with op.batch_alter_table("wompi_pagos") as batch:
        batch.alter_column("wompi_link_id", existing_type=sa.String(64), nullable=True)
        batch.alter_column("checkout_url", existing_type=sa.String(512), nullable=True)
    predicate = sa.text("estado IN ('CREANDO', 'INCIERTO', 'PENDIENTE', 'FALLIDO')")
    op.create_index("uq_wompi_pago_cuota_abierto", "wompi_pagos", ["cuota_id"], unique=True,
                    postgresql_where=predicate, sqlite_where=predicate)


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM wompi_pagos WHERE wompi_link_id IS NULL OR checkout_url IS NULL LIMIT 1")).first():
        raise RuntimeError("Hay intentos sin link confirmado; no se puede revertir la migración.")
    op.drop_index("uq_wompi_pago_cuota_abierto", table_name="wompi_pagos")
    with op.batch_alter_table("wompi_pagos") as batch:
        batch.alter_column("wompi_link_id", existing_type=sa.String(64), nullable=False)
        batch.alter_column("checkout_url", existing_type=sa.String(512), nullable=False)
