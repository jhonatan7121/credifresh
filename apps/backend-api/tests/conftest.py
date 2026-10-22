"""Pytest configuration for backend API integration tests.

The tests run against an in-memory SQLite database so that no production data
is touched. The original get_db dependency from app.config.database is
overridden to yield a session bound to this test engine.
"""

from __future__ import annotations

import os

# The isolated test database explicitly opts into simulated bank operations.
os.environ["BANK_OPERATIONS_ENABLED"] = "true"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import delete
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi import Depends
from sqlalchemy.orm import Session

from main import app
from app.config.database import Base
from app.config.database import get_db as prod_get_db

from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.perfil_financiero import PerfilFinanciero
from app.models.evaluacion import Evaluacion
from app.models.amortizacion import CuotaAmortizacion
from app.models.pago import Pago
from app.models.audit_log import AuditLog
from app.models.notificacion import Notificacion
from app.models.usuario import Usuario

from app.core.deps import get_current_user, get_current_active_user
from app.core.rate_limit import auth_rate_limit_windows
from app.core.security import get_password_hash


# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine,
)

Base.metadata.create_all(bind=test_engine)


def override_get_db():
    """Yield a session bound to the test engine."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Authentication bypass used by legacy tests
# ---------------------------------------------------------------------------

def override_get_current_user(db: Session = Depends(override_get_db)):
    """Return the dedicated bypass ADMIN user from the test database."""
    usuario = (
        db.query(Usuario)
        .filter(Usuario.email == "bypass_admin@credifresh.com")
        .first()
    )
    return usuario


# ---------------------------------------------------------------------------
# Session-level TestClient
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def client() -> TestClient:
    """Return a FastAPI TestClient using the SQLite test database."""

    app.dependency_overrides[prod_get_db] = override_get_db

    db = TestSessionLocal()
    try:
        bypass_user = (
            db.query(Usuario)
            .filter(Usuario.email == "bypass_admin@credifresh.com")
            .first()
        )

        if not bypass_user:
            bypass_user = Usuario(
                email="bypass_admin@credifresh.com",
                password_hash=get_password_hash("PruebaSegura123"),
                rol="ADMIN",
                activo=True,
            )
            db.add(bypass_user)
            db.commit()
            db.refresh(bypass_user)

            bypass_cliente = Cliente(
                nombre="Bypass Admin Cliente",
                cedula="7777777",
                telefono="3007777777",
                usuario_id=bypass_user.id,
            )
            db.add(bypass_cliente)
            db.commit()

    finally:
        db.close()

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_current_active_user] = override_get_current_user

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.pop(prod_get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Dependency override isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_dependency_overrides(client):
    """Prevent one test from contaminating dependency overrides of another."""

    original_overrides = app.dependency_overrides.copy()
    db = TestSessionLocal()
    db.execute(delete(auth_rate_limit_windows))
    db.commit()
    db.close()

    try:
        yield
    finally:
        db = TestSessionLocal()
        db.execute(delete(auth_rate_limit_windows))
        db.commit()
        db.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
