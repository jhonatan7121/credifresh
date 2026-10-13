"""Integración de CrediFresh contra PostgreSQL exclusivamente de pruebas."""

import os
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_NAME = "credifresh_test_db"
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _test_database_url() -> str:
    database_url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("POSTGRES_TEST_DATABASE_URL es obligatorio para estas pruebas.")
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("POSTGRES_TEST_DATABASE_URL debe usar PostgreSQL; SQLite no está permitido.")
    if url.database != TEST_DATABASE_NAME:
        raise RuntimeError("POSTGRES_TEST_DATABASE_URL debe apuntar exclusivamente a credifresh_test_db.")
    return database_url


POSTGRES_TEST_DATABASE_URL = _test_database_url()
# La aplicación y Alembic leen DATABASE_URL. El proceso de pruebas nunca recibe
# la URL de producción: se sustituye antes de importar cualquiera de sus módulos.
os.environ["DATABASE_URL"] = POSTGRES_TEST_DATABASE_URL

from app.config.database import get_db  # noqa: E402
from app.models.cliente import Cliente  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402
from main import app  # noqa: E402


def _assert_test_database(connection) -> None:
    database_name = connection.execute(text("SELECT current_database()")).scalar_one()
    assert database_name == TEST_DATABASE_NAME, "Operación bloqueada fuera de credifresh_test_db"


@pytest.fixture(scope="session", autouse=True)
def setup_postgres_test_db():
    """Crea la base aislada si falta y aplica únicamente migraciones Alembic."""
    test_url = make_url(POSTGRES_TEST_DATABASE_URL)
    admin_engine = create_engine(test_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_DATABASE_NAME},
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}"'))
    finally:
        admin_engine.dispose()

    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("sqlalchemy.url", POSTGRES_TEST_DATABASE_URL)
    command.upgrade(alembic_config, "head")
    yield


@pytest.fixture(scope="session")
def test_engine(setup_postgres_test_db):
    engine = create_engine(POSTGRES_TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            _assert_test_database(connection)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def TestSessionLocal(test_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def clean_db(test_engine):
    """Limpia solo tablas de prueba después de comprobar la base conectada."""
    statement = text(
        "TRUNCATE TABLE pagos, cuotas_amortizacion, notificaciones, evaluaciones, "
        "creditos, perfiles_financieros, clientes, audit_logs, usuarios RESTART IDENTITY CASCADE"
    )
    with test_engine.begin() as connection:
        _assert_test_database(connection)
        connection.execute(statement)
    yield
    with test_engine.begin() as connection:
        _assert_test_database(connection)
        connection.execute(statement)


@pytest.fixture
def db_session(TestSessionLocal):
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def postgres_client(TestSessionLocal):
    def override_get_db():
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    from app.config.database import get_db as prod_get_db
    from app.core.deps import get_current_user, get_current_active_user

    # Guardar overrides de autenticación existentes (pueden venir de conftest.py)
    old_get_db = app.dependency_overrides.get(prod_get_db)
    old_get_current_user = app.dependency_overrides.get(get_current_user)
    old_get_active_user = app.dependency_overrides.get(get_current_active_user)

    # Sobrescribir solo la BD con la de pruebas PostgreSQL
    app.dependency_overrides[prod_get_db] = override_get_db

    # Eliminar overrides de usuario para que se usen las funciones originales
    # (elles leerán el token y consultarán la BD PostgreSQL vía prod_get_db)
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]
    if get_current_active_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_active_user]

    with TestClient(app) as test_client:
        yield test_client

    # Restaurar overrides de autenticación tal como estaban
    if old_get_current_user is not None:
        app.dependency_overrides[get_current_user] = old_get_current_user
    else:
        app.dependency_overrides.pop(get_current_user, None)

    if old_get_active_user is not None:
        app.dependency_overrides[get_current_active_user] = old_get_active_user
    else:
        app.dependency_overrides.pop(get_current_active_user, None)

    # Restaurar el override de BD que estaba activo antes de esta fixture
    if old_get_db is not None:
        app.dependency_overrides[prod_get_db] = old_get_db
    else:
        app.dependency_overrides.pop(prod_get_db, None)


@pytest.fixture
def admin_token(postgres_client, db_session):
    email = "admin.integration@credifresh.test"
    password = "PruebaSegura123"
    register = postgres_client.post("/auth/register", json={"email": email, "password": password, "rol": "ADMIN"})
    assert register.status_code == 201, register.text

    # El endpoint público fuerza CLIENTE; la promoción representa la cuenta
    # administrativa preexistente y se limita a la base aislada de pruebas.
    admin = db_session.query(Usuario).filter(Usuario.email == email).one()
    admin.rol = "ADMIN"
    db_session.commit()

    login = postgres_client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _crear_cliente(client: TestClient, token: str) -> int:
    response = client.post("/clientes/", headers=_headers(token), json={"nombre": "Ana Prueba", "cedula": "1010101010", "telefono": "3001234567"})
    assert response.status_code == 201, response.text
    return response.json()["cliente"]["id"]


def _crear_perfil(client: TestClient, token: str, cliente_id: int) -> None:
    response = client.post(
        f"/clientes/{cliente_id}/perfil-financiero", headers=_headers(token),
        json={"ingresos_mensuales": 10_000_000, "gastos_mensuales": 1_000_000, "otras_obligaciones": 0, "tipo_ingresos": "SALARIO", "actividad_economica": "SERVICIOS"},
    )
    assert response.status_code == 201, response.text


def _crear_credito(client: TestClient, token: str, cliente_id: int) -> int:
    response = client.post(
        "/creditos/", headers=_headers(token),
        json={"cliente_id": cliente_id, "monto": 500_000, "plazo_meses": 6, "tasa_interes": 1},
    )
    assert response.status_code == 201, response.text
    return response.json()["credito"]["id"]


def _credito_aprobado(client: TestClient, token: str) -> int:
    cliente_id = _crear_cliente(client, token)
    _crear_perfil(client, token, cliente_id)
    credito_id = _crear_credito(client, token, cliente_id)
    evaluation = client.post(f"/creditos/{credito_id}/evaluar", headers=_headers(token))
    assert evaluation.status_code == 200, evaluation.text
    assert evaluation.json()["decision"] == "APROBADO"

    email = f"cliente.integration.{credito_id}@credifresh.test"
    register = client.post("/auth/register", json={"email": email, "password": "PruebaSegura123"})
    assert register.status_code == 201, register.text
    linked = client.patch(
        f"/clientes/{cliente_id}/vincular-usuario",
        headers=_headers(token),
        json={"usuario_id": register.json()["id"]},
    )
    assert linked.status_code == 200, linked.text

    login = client.post("/auth/login", json={"email": email, "password": "PruebaSegura123"})
    assert login.status_code == 200, login.text
    client_headers = _headers(login.json()["access_token"])
    my_credits = client.get("/creditos/mis", headers=client_headers)
    assert my_credits.status_code == 200, my_credits.text
    credit = next(item for item in my_credits.json() if item["credito"]["id"] == credito_id)
    accepted = client.post(
        f"/creditos/{credito_id}/aceptar",
        headers=client_headers,
        json={
            "acepta": True,
            "monto": credit["credito"]["monto"],
            "plazo_meses": credit["credito"]["plazo_meses"],
            "tasa_interes": credit["credito"]["tasa_interes"],
            "cuota_mensual": credit["evaluacion"]["cuota_mensual"],
            "total_estimado": credit["total_estimado"],
        },
    )
    assert accepted.status_code == 201, accepted.text
    return credito_id


def test_postgres_connection_and_database_name(test_engine):
    with test_engine.connect() as connection:
        _assert_test_database(connection)
        assert connection.execute(text("SELECT 1")).scalar_one() == 1


def test_creacion_y_lectura_clientes(postgres_client, admin_token):
    cliente_id = _crear_cliente(postgres_client, admin_token)
    response = postgres_client.get(f"/clientes/{cliente_id}", headers=_headers(admin_token))
    assert response.status_code == 200, response.text
    assert response.json()["cedula"] == "1010101010"


def test_perfil_financiero(postgres_client, admin_token):
    cliente_id = _crear_cliente(postgres_client, admin_token)
    _crear_perfil(postgres_client, admin_token, cliente_id)
    response = postgres_client.get(f"/clientes/{cliente_id}/perfil-financiero", headers=_headers(admin_token))
    assert response.status_code == 200, response.text
    assert Decimal(str(response.json()["ingresos_mensuales"])) == Decimal("10000000")


def test_creacion_y_evaluacion_credito(postgres_client, admin_token):
    credito_id = _credito_aprobado(postgres_client, admin_token)
    response = postgres_client.get(f"/creditos/{credito_id}", headers=_headers(admin_token))
    assert response.status_code == 200, response.text
    assert response.json()["estado"] == "APROBADO"


def test_desembolso_y_amortizacion(postgres_client, admin_token):
    credito_id = _credito_aprobado(postgres_client, admin_token)
    disbursement = postgres_client.post(f"/creditos/{credito_id}/desembolsar", headers=_headers(admin_token))
    assert disbursement.status_code == 200, disbursement.text
    assert disbursement.json()["credito"]["estado"] == "DESEMBOLSADO"
    amortization = postgres_client.get(f"/creditos/{credito_id}/amortizacion", headers=_headers(admin_token))
    assert amortization.status_code == 200, amortization.text
    assert len(amortization.json()) == 6


def test_registro_pagos(postgres_client, admin_token):
    credito_id = _credito_aprobado(postgres_client, admin_token)
    assert postgres_client.post(f"/creditos/{credito_id}/desembolsar", headers=_headers(admin_token)).status_code == 200
    cuotas = postgres_client.get(f"/creditos/{credito_id}/amortizacion", headers=_headers(admin_token)).json()
    payment = postgres_client.post(
        f"/creditos/{credito_id}/pagos", headers=_headers(admin_token),
        json={"monto": cuotas[0]["monto_cuota"], "metodo_pago": "TRANSFERENCIA"},
    )
    assert payment.status_code == 200, payment.text
    assert payment.json()["distribucion_pagos"][0]["cuota_estado_resultante"] == "PAGADA"
    history = postgres_client.get(f"/creditos/{credito_id}/pagos", headers=_headers(admin_token))
    assert history.status_code == 200, history.text
    assert len(history.json()) == 1


def test_rollback_transaccional(db_session):
    client = Cliente(nombre="Temporal", cedula="2020202020", telefono="3009876543")
    db_session.add(client)
    db_session.flush()
    client_id = client.id
    db_session.rollback()
    assert db_session.get(Cliente, client_id) is None
