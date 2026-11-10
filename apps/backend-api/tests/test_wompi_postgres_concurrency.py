"""Payment-link concurrency against the explicitly isolated PostgreSQL database."""

import datetime
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import wompi as endpoint
from app.models.amortizacion import CuotaAmortizacion
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.usuario import Usuario
from app.models.wompi_pago import WompiPago


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
