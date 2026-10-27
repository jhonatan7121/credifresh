"""Seed disposable synthetic records for the isolated Wompi Sandbox deployment."""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import SessionLocal
from app.core.security import get_password_hash, verify_password
from app.models.amortizacion import CuotaAmortizacion
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.usuario import Usuario


SEED_EMAIL = "cliente.wompi.test@credifresh.invalid"
SEED_PHONE = "3000000000"
SEED_ADDRESS = "Direccion ficticia para pruebas Sandbox"


def ensure_sandbox_test_records(db, client: Cliente) -> bool:
    """Keep the disposable sandbox user ready for repeatable payment tests.

    Render's sandbox uses an ephemeral SQLite file, so each fresh instance must
    reconstruct a complete synthetic profile and a pending quota for the
    decline-path test. This is intentionally limited to the seeded test user.
    """
    changed = False
    if not client.telefono or not client.telefono.strip().isdigit() or len(client.telefono.strip()) < 7:
        client.telefono = SEED_PHONE
        changed = True
    if not client.direccion or len(client.direccion.strip()) < 5:
        client.direccion = SEED_ADDRESS
        changed = True

    credits = (
        db.query(Credito)
        .filter(Credito.cliente_id == client.id)
        .order_by(Credito.id.asc())
        .all()
    )
    if not credits:
        raise SystemExit("Existing sandbox seed is incomplete; refusing to alter records.")

    # The first seeded quota is used for the approved-payment path. Keep a
    # second, independent pending quota for the declined-payment path.
    if len(credits) < 2:
        credit = Credito(
            cliente_id=client.id,
            monto=Decimal("100000.00"),
            plazo_meses=1,
            tasa_interes=Decimal("0.00"),
            estado="DESEMBOLSADO",
        )
        db.add(credit)
        db.flush()
        db.add(CuotaAmortizacion(
            credito_id=credit.id,
            numero_cuota=1,
            fecha_vencimiento=datetime.now(timezone.utc) + timedelta(days=30),
            monto_cuota=Decimal("100000.00"),
            capital=Decimal("100000.00"),
            interes=Decimal("0.00"),
            saldo_remanente=Decimal("0.00"),
            monto_pagado=Decimal("0.00"),
            estado="PENDIENTE",
        ))
        changed = True

    return changed


def main() -> None:
    if os.getenv("ENVIRONMENT", "").strip().lower() != "sandbox":
        raise SystemExit("Refusing to seed outside ENVIRONMENT=sandbox.")
    if os.getenv("WOMPI_ENVIRONMENT", "").strip().lower() != "sandbox":
        raise SystemExit("Refusing to seed unless WOMPI_ENVIRONMENT=sandbox.")
    if os.getenv("WOMPI_SANDBOX_SEED_DATA", "").strip().lower() != "true":
        raise SystemExit("Refusing to seed without WOMPI_SANDBOX_SEED_DATA=true.")
    password = os.getenv("WOMPI_SANDBOX_TEST_PASSWORD", "")
    if len(password) < 16:
        raise SystemExit("WOMPI_SANDBOX_TEST_PASSWORD must be at least 16 characters.")

    db = SessionLocal()
    try:
        existing = db.query(Usuario).filter(Usuario.email == SEED_EMAIL).first()
        if existing:
            linked_client = db.query(Cliente).filter(Cliente.usuario_id == existing.id).first()
            if not linked_client or not db.query(Credito).filter( Credito.cliente_id == linked_client.id).first():
                raise SystemExit("Existing sandbox seed is incomplete; refusing to alter records.")
            # Keep the disposable test user's password aligned with Render's secret after rotation.
            if not verify_password(password, existing.password_hash):
                existing.password_hash = get_password_hash(password)
                existing.auth_token_version += 1
                changed = True
            else:
                changed = False
            changed = ensure_sandbox_test_records(db, linked_client) or changed
            if changed:
                db.commit()
            return

        user = Usuario(
            email=SEED_EMAIL,
            password_hash=get_password_hash(password),
            rol="CLIENTE",
            activo=True,
        )
        db.add(user)
        db.flush()
        client = Cliente(
            nombre="Cliente de prueba Wompi",
            cedula="SANDBOX-WOMPI-001",
            telefono=SEED_PHONE,
            direccion=SEED_ADDRESS,
            email=SEED_EMAIL,
            usuario_id=user.id,
        )
        db.add(client)
        db.flush()
        credit = Credito(
            cliente_id=client.id,
            monto=Decimal("100000.00"),
            plazo_meses=1,
            tasa_interes=Decimal("0.00"),
            estado="DESEMBOLSADO",
        )
        db.add(credit)
        db.flush()
        db.add(CuotaAmortizacion(
            credito_id=credit.id,
            numero_cuota=1,
            fecha_vencimiento=datetime.now(timezone.utc) + timedelta(days=30),
            monto_cuota=Decimal("100000.00"),
            capital=Decimal("100000.00"),
            interes=Decimal("0.00"),
            saldo_remanente=Decimal("0.00"),
            monto_pagado=Decimal("0.00"),
            estado="PENDIENTE",
        ))
        ensure_sandbox_test_records(db, client)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
