"""Payment-link concurrency against the explicitly isolated PostgreSQL database."""

import datetime
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import wompi as endpoint
from app.models.amortizacion import CuotaAmortizacion
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.usuario import Usuario
from app.models.wompi_pago import WompiPago
from app.models.pago import Pago
from app.models.audit_log import AuditLog
from app.models.wompi_reembolso import WompiReembolsoSandbox


def isolated_engine():
    url = make_url(os.environ["POSTGRES_TEST_DATABASE_URL"])
    if (not url.drivername.startswith("postgresql") or url.host not in {"localhost", "127.0.0.1"}
            or url.port != 5434 or url.database != "credifresh_test_db"):
        raise RuntimeError("La prueba exige PostgreSQL local aislado en 127.0.0.1:5434/credifresh_test_db.")
    return create_engine(url, pool_pre_ping=True)


@pytest.mark.skipif(not os.getenv("POSTGRES_TEST_DATABASE_URL"), reason="Requiere PostgreSQL local aislado")
def test_solicitudes_simultaneas_no_crean_dos_links(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_test_local_ficticia")
    engine = isolated_engine()
    Session = sessionmaker(bind=engine, autoflush=False)
    unique = uuid4().hex
    db = Session()
    try:
        user = Usuario(email=f"pg-{unique}@example.invalid", password_hash="x", rol="CLIENTE", activo=True)
        db.add(user)
        db.flush()
        person = Cliente(nombre="Cliente ficticio", cedula=unique[:12], telefono="3000000000", usuario_id=user.id)
        db.add(person)
        db.flush()
        credit = Credito(cliente_id=person.id, monto=Decimal("1250.00"), plazo_meses=1,
                         tasa_interes=Decimal("0"), estado="DESEMBOLSADO")
        db.add(credit)
        db.flush()
        quota = CuotaAmortizacion(credito_id=credit.id, numero_cuota=1,
            fecha_vencimiento=datetime.datetime(2026, 12, 1), monto_cuota=Decimal("1250.00"),
            capital=Decimal("1250.00"), interes=Decimal("0"), saldo_remanente=Decimal("0"),
            monto_pagado=Decimal("0"), estado="PENDIENTE")
        db.add(quota)
        db.commit()
        credit_id, quota_id, user_id = credit.id, quota.id, user.id
    finally:
        db.close()

    started, finish = threading.Event(), threading.Event()
    calls = []

    def fake_wompi(**_kwargs):
        calls.append(1)
        started.set()
        assert finish.wait(10)
        return {"id": f"link-{unique}", "checkout_url": f"https://checkout.wompi.co/l/{unique}", "ambiente": "sandbox"}

    monkeypatch.setattr(endpoint, "crear_link_pago", fake_wompi)

    def request_link():
        session = Session()
        try:
            return endpoint.crear_link_para_cuota(credit_id, quota_id, session, session.get(Usuario, user_id))
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request_link)
            assert started.wait(10)
            second = pool.submit(request_link)
            try:
                with pytest.raises(HTTPException) as exc:
                    second.result(timeout=10)
                assert exc.value.status_code == 409
            finally:
                finish.set()
            assert first.result(timeout=10)["checkout_url"].endswith(unique)
        with Session() as session:
            assert session.query(WompiPago).filter_by(cuota_id=quota_id).count() == 1
        assert len(calls) == 1
    finally:
        engine.dispose()


@pytest.mark.skipif(not os.getenv("POSTGRES_TEST_DATABASE_URL"), reason="Requiere PostgreSQL local aislado")
def test_migracion_postgres_rechaza_duplicados_sin_alterarlos():
    # Only the disposable server selected by isolated_engine can create this
    # separate synthetic migration database. No external database is touched.
    engine = isolated_engine()
    source_url = engine.url
    engine.dispose()
    db_name = f"credifresh_migration_{uuid4().hex[:12]}"
    admin = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        admin.dispose()

    migration_url = source_url.set(database=db_name)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = migration_url.render_as_string(hide_password=False)
    command = [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade"]
    subprocess.run(command + ["12da730bf081"], env=environment, check=True, capture_output=True)
    migration_engine = create_engine(migration_url)
    Session = sessionmaker(bind=migration_engine, autoflush=False)
    try:
        with Session() as db:
            user = Usuario(email="migration@example.invalid", password_hash="x", rol="CLIENTE", activo=True)
            db.add(user)
            db.flush()
            person = Cliente(nombre="Cliente ficticio", cedula="12345678", telefono="3000000000", usuario_id=user.id)
            db.add(person)
            db.flush()
            credit = Credito(cliente_id=person.id, monto=Decimal("1250.00"), plazo_meses=1,
                             tasa_interes=Decimal("0"), estado="DESEMBOLSADO")
            db.add(credit)
            db.flush()
            quota = CuotaAmortizacion(credito_id=credit.id, numero_cuota=1,
                fecha_vencimiento=datetime.datetime(2026, 12, 1), monto_cuota=Decimal("1250.00"),
                capital=Decimal("1250.00"), interes=Decimal("0"), saldo_remanente=Decimal("0"),
                monto_pagado=Decimal("0"), estado="PENDIENTE")
            db.add(quota)
            db.flush()
            for i in (1, 2):
                db.add(WompiPago(credito_id=credit.id, cuota_id=quota.id, referencia=f"ref-{i}",
                                 wompi_link_id=f"link-{i}", monto_esperado=Decimal("1250.00"),
                                 estado="PENDIENTE", checkout_url=f"https://example.invalid/{i}"))
            db.commit()
        result = subprocess.run(command + ["head"], env=environment, capture_output=True, text=True)
        assert result.returncode != 0
        assert "intentos abiertos" in result.stderr
        with migration_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM wompi_pagos")).scalar_one() == 2
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "12da730bf081"
        columns = {column["name"]: column for column in inspect(migration_engine).get_columns("wompi_pagos")}
        assert columns["wompi_link_id"]["nullable"] is False
    finally:
        migration_engine.dispose()


@pytest.mark.skipif(not os.getenv("POSTGRES_TEST_DATABASE_URL"), reason="Requiere PostgreSQL local aislado")
def test_webhook_y_reconciliacion_simultaneos_aplican_un_solo_pago(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_test_local_ficticia")
    monkeypatch.setenv("WOMPI_EVENTS_SECRET", "test_events_ficticio")
    engine = isolated_engine()
    Session = sessionmaker(bind=engine, autoflush=False)
    unique = uuid4().hex
    tx_id, link_id = f"tx-{unique}", f"link-{unique}"
    db = Session()
    try:
        admin = Usuario(email=f"admin-{unique}@example.invalid", password_hash="x", rol="ADMIN", activo=True)
        db.add(admin)
        db.flush()
        person = Cliente(nombre="Cliente ficticio", cedula=unique[:12], telefono="3000000000", usuario_id=admin.id)
        db.add(person)
        db.flush()
        credit = Credito(cliente_id=person.id, monto=Decimal("1250.00"), plazo_meses=1,
                         tasa_interes=Decimal("0"), estado="DESEMBOLSADO")
        db.add(credit)
        db.flush()
        quota = CuotaAmortizacion(credito_id=credit.id, numero_cuota=1,
            fecha_vencimiento=datetime.datetime(2026, 12, 1), monto_cuota=Decimal("1250.00"),
            capital=Decimal("1250.00"), interes=Decimal("0"), saldo_remanente=Decimal("0"),
            monto_pagado=Decimal("0"), estado="PENDIENTE")
        db.add(quota)
        db.flush()
        db.add(WompiPago(credito_id=credit.id, cuota_id=quota.id, referencia=unique,
                         wompi_link_id=link_id, monto_esperado=Decimal("1250.00"),
                         estado="PENDIENTE", checkout_url=f"https://checkout.wompi.co/l/{unique}"))
        db.commit()
        credit_id, quota_id, admin_id = credit.id, quota.id, admin.id
    finally:
        db.close()

    transaction = {"id": tx_id, "payment_link_id": link_id, "status": "APPROVED",
                   "amount_in_cents": 125000, "currency": "COP"}
    sync = threading.Barrier(2, timeout=10)
    def consult(_id):
        sync.wait()
        return transaction.copy()
    monkeypatch.setattr(endpoint, "consultar_transaccion", consult)

    def webhook():
        timestamp = 1794300000
        digest = hashlib.sha256(f"{tx_id}APPROVED125000{timestamp}test_events_ficticio".encode()).hexdigest()
        event = {"event": "transaction.updated", "environment": "test", "timestamp": timestamp,
                 "data": {"transaction": transaction},
                 "signature": {"properties": ["transaction.id", "transaction.status", "transaction.amount_in_cents"],
                               "checksum": digest}}
        async def receive():
            return {"type": "http.request", "body": json.dumps(event).encode(), "more_body": False}
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}, receive)
        session = Session()
        try:
            return asyncio.run(endpoint.recibir_evento_sandbox(request, session, digest))
        finally:
            session.close()

    def reconcile():
        session = Session()
        try:
            return endpoint.reconciliar_cuota_sandbox(credit_id, quota_id,
                endpoint.ReconciliacionSandbox(transaction_id=tx_id), session, session.get(Usuario, admin_id))
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(webhook), pool.submit(reconcile)
            first.result(timeout=20)
            second.result(timeout=20)
        with Session() as session:
            assert session.query(Pago).filter_by(credito_id=credit_id, cuota_id=quota_id).count() == 1
            assert session.get(CuotaAmortizacion, quota_id).monto_pagado == Decimal("1250.00")
    finally:
        engine.dispose()


@pytest.mark.skipif(not os.getenv("POSTGRES_TEST_DATABASE_URL"), reason="Requiere PostgreSQL local aislado")
def test_cambio_de_estado_concurrente_registra_una_sola_alerta():
    engine = isolated_engine()
    Session = sessionmaker(bind=engine, autoflush=False)
    unique = uuid4().hex
    transaction = {"id": f"tx-{unique}", "payment_link_id": f"link-{unique}",
                   "status": "VOIDED", "amount_in_cents": 125000, "currency": "COP"}
    try:
        with Session() as db:
            user = Usuario(email=f"alert-{unique}@example.invalid", password_hash="x", rol="CLIENTE", activo=True)
            db.add(user)
            db.flush()
            person = Cliente(nombre="Prueba", cedula=unique[:12], telefono="3000000000", usuario_id=user.id)
            db.add(person)
            db.flush()
            credit = Credito(cliente_id=person.id, monto=Decimal("1250"), plazo_meses=1, tasa_interes=Decimal("0"), estado="DESEMBOLSADO")
            db.add(credit)
            db.flush()
            quota = CuotaAmortizacion(credito_id=credit.id, numero_cuota=1, fecha_vencimiento=datetime.datetime(2026, 12, 1),
                monto_cuota=Decimal("1250"), capital=Decimal("1250"), interes=Decimal("0"), saldo_remanente=Decimal("0"),
                monto_pagado=Decimal("1250"), estado="PAGADA")
            db.add(quota)
            db.flush()
            attempt = WompiPago(credito_id=credit.id, cuota_id=quota.id, referencia=unique,
                wompi_link_id=transaction["payment_link_id"], wompi_transaction_id=transaction["id"],
                monto_esperado=Decimal("1250"), estado="PAGADO", checkout_url=f"https://example.invalid/{unique}")
            db.add(attempt)
            db.flush()
            attempt_id, quota_id = attempt.id, quota.id
            db.commit()
        start = threading.Barrier(2, timeout=10)
        def process():
            with Session() as session:
                start.wait()
                return endpoint._aplicar_transaccion_verificada(session, transaction, "sandbox")
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(process), pool.submit(process)
            assert first.result(timeout=20)["requiere_revision"]
            assert second.result(timeout=20)["requiere_revision"]
        with Session() as db:
            assert db.query(AuditLog).filter_by(accion="ALERTA_CAMBIO_ESTADO_WOMPI", entidad="wompi_pago", entidad_id=attempt_id).count() == 1
            assert db.get(CuotaAmortizacion, quota_id).monto_pagado == Decimal("1250.00")
    finally:
        engine.dispose()


@pytest.mark.skipif(not os.getenv("POSTGRES_TEST_DATABASE_URL"), reason="Requiere PostgreSQL local aislado")
def test_dos_reembolsos_simultaneos_solo_envian_uno(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "sandbox")
    engine = isolated_engine()
    Session = sessionmaker(bind=engine, autoflush=False)
    unique = uuid4().hex
    transaction = {"id": f"tx-{unique}", "payment_link_id": f"link-{unique}",
                   "status": "APPROVED", "amount_in_cents": 125000, "currency": "COP"}
    try:
        with Session() as db:
            admin = Usuario(email=f"refund-{unique}@example.invalid", password_hash="x", rol="ADMIN", activo=True)
            db.add(admin)
            db.flush()
            person = Cliente(nombre="Prueba", cedula=unique[:12], telefono="3000000000", usuario_id=admin.id)
            db.add(person)
            db.flush()
            credit = Credito(cliente_id=person.id, monto=Decimal("1250"), plazo_meses=1, tasa_interes=Decimal("0"), estado="DESEMBOLSADO")
            db.add(credit)
            db.flush()
            quota = CuotaAmortizacion(credito_id=credit.id, numero_cuota=1, fecha_vencimiento=datetime.datetime(2026, 12, 1),
                monto_cuota=Decimal("1250"), capital=Decimal("1250"), interes=Decimal("0"), saldo_remanente=Decimal("0"),
                monto_pagado=Decimal("1250"), estado="PAGADA")
            db.add(quota)
            db.flush()
            attempt = WompiPago(credito_id=credit.id, cuota_id=quota.id, referencia=unique,
                wompi_link_id=transaction["payment_link_id"], wompi_transaction_id=transaction["id"],
                monto_esperado=Decimal("1250"), estado="PAGADO", checkout_url=f"https://example.invalid/{unique}")
            db.add(attempt)
            db.add(Pago(credito_id=credit.id, cuota_id=quota.id, monto_pagado=Decimal("1250"), metodo_pago="WOMPI_SANDBOX"))
            db.commit()
            credit_id, quota_id, admin_id, attempt_id = credit.id, quota.id, admin.id, attempt.id
        monkeypatch.setattr(endpoint, "consultar_transaccion", lambda _id: transaction)
        started, release = threading.Event(), threading.Event()
        calls = []
        def provider(**kwargs):
            calls.append(1)
            started.set()
            assert release.wait(10)
            return {"status": "APPROVED", "refund_id": "sandbox-refund"}
        monkeypatch.setattr(endpoint, "solicitar_reembolso_sandbox", provider)
        def request_refund():
            with Session() as session:
                return endpoint.crear_reembolso_de_prueba(credit_id, quota_id,
                    endpoint.ReembolsoSandboxInput(monto_centavos=10000, escenario="approved"),
                    session, session.get(Usuario, admin_id))
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request_refund)
            assert started.wait(10)
            second = pool.submit(request_refund)
            try:
                assert second.result(timeout=10)["ya_existia"] is True
            finally:
                release.set()
            assert first.result(timeout=10)["estado"] == "CONFIRMADO"
        with Session() as db:
            assert db.query(WompiReembolsoSandbox).filter_by(wompi_pago_id=attempt_id).count() == 1
            assert db.get(CuotaAmortizacion, quota_id).monto_pagado == Decimal("1250")
        assert len(calls) == 1
    finally:
        engine.dispose()


@pytest.mark.skipif(not os.getenv("POSTGRES_TEST_DATABASE_URL"), reason="Requiere PostgreSQL local aislado")
def test_reconciliacion_reembolso_concurrente_registra_una_auditoria(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "sandbox")
    engine = isolated_engine()
    Session = sessionmaker(bind=engine, autoflush=False)
    unique = uuid4().hex
    transaction_id = f"tx-{unique}"
    try:
        with Session() as db:
            admin = Usuario(email=f"reconcile-{unique}@example.invalid", password_hash="x", rol="ADMIN", activo=True)
            db.add(admin); db.flush()
            person = Cliente(nombre="Prueba", cedula=unique[:12], telefono="3000000000", usuario_id=admin.id)
            db.add(person); db.flush()
            credit = Credito(cliente_id=person.id, monto=Decimal("1250"), plazo_meses=1, tasa_interes=Decimal("0"), estado="DESEMBOLSADO")
            db.add(credit); db.flush()
            quota = CuotaAmortizacion(credito_id=credit.id, numero_cuota=1, fecha_vencimiento=datetime.datetime(2026, 12, 1),
                monto_cuota=Decimal("1250"), capital=Decimal("1250"), interes=Decimal("0"), saldo_remanente=Decimal("0"),
                monto_pagado=Decimal("1250"), estado="PAGADA")
            db.add(quota); db.flush()
            payment = WompiPago(credito_id=credit.id, cuota_id=quota.id, referencia=unique,
                wompi_link_id=f"link-{unique}", wompi_transaction_id=transaction_id,
                monto_esperado=Decimal("1250"), estado="PAGADO", checkout_url=f"https://example.invalid/{unique}")
            db.add(payment); db.flush()
            db.add(WompiReembolsoSandbox(wompi_pago_id=payment.id, referencia=uuid4().hex,
                monto=Decimal("100"), escenario="approved", estado="INCIERTO"))
            db.add(Pago(credito_id=credit.id, cuota_id=quota.id, monto_pagado=Decimal("1250"), metodo_pago="WOMPI_SANDBOX"))
            db.commit()
            credit_id, quota_id, admin_id, payment_id = credit.id, quota.id, admin.id, payment.id
        started, release = threading.Event(), threading.Event()
        calls = []
        def provider(_id):
            calls.append(1); started.set()
            assert release.wait(10)
            return {"respuesta_http_wompi": 200, "datos_confirmados": True, "estado": "APPROVED",
                    "monto_centavos": 10000, "transaction_id": transaction_id}
        monkeypatch.setattr(endpoint, "consultar_reembolso_sandbox", provider)
        def reconcile():
            with Session() as session:
                return endpoint.reconciliar_reembolso_sandbox(credit_id, quota_id,
                    endpoint.ReconciliarReembolsoSandboxInput(refund_id="32935"), session, session.get(Usuario, admin_id))
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(reconcile)
            assert started.wait(10)
            second = pool.submit(reconcile)
            release.set()
            results = [first.result(timeout=10), second.result(timeout=10)]
        assert sorted(item["ya_reconciliado"] for item in results) == [False, True]
        assert len(calls) == 1
        with Session() as db:
            assert db.query(WompiReembolsoSandbox).filter_by(wompi_pago_id=payment_id).one().estado == "CONFIRMADO"
            assert db.query(AuditLog).filter_by(accion="RECONCILIAR_REEMBOLSO_WOMPI_SANDBOX", entidad_id=credit_id).count() == 1
            assert db.get(CuotaAmortizacion, quota_id).monto_pagado == Decimal("1250")
            assert db.query(Pago).filter_by(credito_id=credit_id, cuota_id=quota_id).count() == 1
    finally:
        engine.dispose()
