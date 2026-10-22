"""Seed disposable synthetic records for the isolated Wompi Sandbox deployment."""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import SessionLocal
from app.core.security import get_password_hash
from app.models.amortizacion import CuotaAmortizacion
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.usuario import Usuario


SEED_EMAIL = "cliente.wompi.test@credifresh.invalid"


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
            if not linked_client or not db.query(Credito).filter(Credito.cliente_id == linked_client.id).first():
                raise SystemExit("Existing sandbox seed is incomplete; refusing to alter records.")
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
            telefono="3000000000",
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
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()


