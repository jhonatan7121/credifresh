from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from app.models.amortizacion import CuotaAmortizacion
from app.models.cliente import Cliente
from app.models.credito import Credito
from conftest import TestSessionLocal
from scripts.seed_wompi_sandbox import ensure_sandbox_test_records


def test_seed_fills_synthetic_address_and_adds_one_pending_decline_quota():
    db = TestSessionLocal()
    client = Cliente(
        nombre="Wompi seed test",
        cedula=str(uuid4().int)[:20],
        telefono="3000000000",
        direccion=None,
    )
    db.add(client)
    db.flush()
    approved_credit = Credito(
        cliente_id=client.id,
        monto=Decimal("100000.00"),
        plazo_meses=1,
        tasa_interes=Decimal("0.00"),
        estado="PAGADO",
    )
    db.add(approved_credit)
    db.flush()
    db.add(CuotaAmortizacion(
        credito_id=approved_credit.id,
        numero_cuota=1,
        fecha_vencimiento=datetime.now(timezone.utc) + timedelta(days=30),
        monto_cuota=Decimal("100000.00"),
        capital=Decimal("100000.00"),
        interes=Decimal("0.00"),
        saldo_remanente=Decimal("0.00"),
        monto_pagado=Decimal("100000.00"),
        estado="PAGADA",
    ))
    db.commit()

    try:
        assert ensure_sandbox_test_records(db, client) is True
        db.commit()
        db.refresh(client)
        assert client.direccion == "Direccion ficticia para pruebas Sandbox"

        credits = db.query(Credito).filter(Credito.cliente_id == client.id).order_by(Credito.id).all()
        assert len(credits) == 2
        assert credits[0].estado == "PAGADO"
        assert credits[1].estado == "DESEMBOLSADO"

        decline_quota = (
            db.query(CuotaAmortizacion)
            .filter(CuotaAmortizacion.credito_id == credits[1].id)
            .one()
        )
        assert decline_quota.estado == "PENDIENTE"
        assert decline_quota.monto_pagado == Decimal("0.00")

        assert ensure_sandbox_test_records(db, client) is False
        assert db.query(Credito).filter(Credito.cliente_id == client.id).count() == 2
    finally:
        credit_ids = [
            row.id for row in db.query(Credito).filter(Credito.cliente_id == client.id).all()
        ]
        if credit_ids:
            db.query(CuotaAmortizacion).filter(CuotaAmortizacion.credito_id.in_(credit_ids)).delete(
                synchronize_session=False
            )
            db.query(Credito).filter(Credito.id.in_(credit_ids)).delete(synchronize_session=False)
        db.query(Cliente).filter(Cliente.id == client.id).delete(synchronize_session=False)
        db.commit()
        db.close()
