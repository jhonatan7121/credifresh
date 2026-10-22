import hashlib
import os
import datetime
import json

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "wompi-route-test-secret-not-for-production")

from decimal import Decimal

from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import wompi as wompi_endpoint
from app.config.database import Base
from app.models.amortizacion import CuotaAmortizacion
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.pago import Pago
from app.models.usuario import Usuario
from app.models.wompi_pago import WompiPago


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(bind=engine)


def make_event(secret="test_events_route"):
    event = {
        "event": "transaction.updated",
        "data": {"transaction": {
            "id": "route-tx-001",
            "status": "APPROVED",
            "amount_in_cents": 125000,
            "currency": "COP",
            "payment_link_id": "route-link-001",
        }},
        "environment": "test",
        "signature": {"properties": [
            "transaction.id", "transaction.status", "transaction.amount_in_cents",
        ]},
        "timestamp": 1792600000,
    }
    raw = "route-tx-001APPROVED1250001792600000" + secret
    event["signature"]["checksum"] = hashlib.sha256(raw.encode()).hexdigest()
    return event


def call_webhook(event, checksum=None):
    body = json.dumps(event).encode()
    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.request", "body": b"", "more_body": False}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/integraciones/wompi/sandbox/eventos", "headers": [], "query_string": b""}, receive)
    db = Session()
    try:
        coroutine = wompi_endpoint.recibir_evento_sandbox(request, db, checksum)
        try:
            coroutine.send(None)
        except StopIteration as result:
            return result.value
        raise AssertionError("El handler de prueba pidió una operación asíncrona externa inesperada.")
    finally:
        db.close()


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    os.environ["ENVIRONMENT"] = "test"
    os.environ["WOMPI_ENVIRONMENT"] = "sandbox"
    os.environ["WOMPI_PRIVATE_KEY"] = "prv_test_route"
    os.environ["WOMPI_EVENTS_SECRET"] = "test_events_route"
    user = Usuario(email="client@example.test", password_hash="not-used", rol="CLIENTE", activo=True)
    db = Session()
    db.add(user)
    db.flush()
    client_record = Cliente(nombre="Sandbox Client", cedula="100000001", telefono="3000000000", usuario_id=user.id)
    db.add(client_record)
    db.flush()
    credit = Credito(cliente_id=client_record.id, monto=Decimal("1250.00"), plazo_meses=1, tasa_interes=Decimal("0"), estado="DESEMBOLSADO")
    db.add(credit)
    db.flush()
    quota = CuotaAmortizacion(
        credito_id=credit.id, numero_cuota=1, fecha_vencimiento=datetime.datetime(2026, 11, 1),
        monto_cuota=Decimal("1250.00"), capital=Decimal("1250.00"), interes=Decimal("0"),
        saldo_remanente=Decimal("0"), monto_pagado=Decimal("0"), estado="PENDIENTE",
    )
    db.add(quota)
    db.flush()
    intent = WompiPago(
        credito_id=credit.id, cuota_id=quota.id, referencia="internal-route-ref",
        wompi_link_id="route-link-001", monto_esperado=Decimal("1250.00"),
        estado="PENDIENTE", checkout_url="https://checkout.wompi.co/l/route-link-001",
    )
    db.add(intent)
    db.commit()
    db.close()


def test_webhook_aplica_pago_aprobado_y_es_idempotente():
    event = make_event()
    checksum = event["signature"]["checksum"]
    first = call_webhook(event, checksum)
    second = call_webhook(event, checksum)
    assert first["estado"] == "PAGADO"
    assert second["duplicado"] is True
    db = Session()
    try:
        assert db.query(Pago).count() == 1
        assert db.query(CuotaAmortizacion).one().estado == "PAGADA"
        assert db.query(WompiPago).one().wompi_transaction_id == "route-tx-001"
    finally:
        db.close()


def test_webhook_rechaza_firma_invalida_sin_aplicar_pago():
    event = make_event()
    event["signature"]["checksum"] = "0" * 64
    with pytest.raises(HTTPException) as exc:
        call_webhook(event)
    assert exc.value.status_code == 401
    db = Session()
    try:
        assert db.query(Pago).count() == 0
        assert db.query(CuotaAmortizacion).one().monto_pagado == Decimal("0.00")
    finally:
        db.close()


def test_crear_link_reutiliza_intento_pendiente(monkeypatch):
    monkeypatch.setattr(wompi_endpoint, "crear_link_pago", lambda **_kwargs: pytest.fail("no debe generar un link duplicado"))
    db = Session()
    try:
        credit = db.query(Credito).one()
        quota = db.query(CuotaAmortizacion).one()
        user = db.query(Usuario).one()
        result = wompi_endpoint.crear_link_para_cuota(credit.id, quota.id, db, user)
    finally:
        db.close()
    assert result["checkout_url"].endswith("route-link-001")
