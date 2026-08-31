"""Pytest configuration for backend API integration tests.

The tests run against an **in‑memory SQLite** database so that no production data
is touched.  The original ``get_db`` dependency from
``app.config.database`` is overridden to yield a session bound to this test
engine.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

# Import the application and the original database objects
from main import app
from app.config.database import Base
from app.config.database import get_db as prod_get_db

# Import models to register their tables on Base.metadata
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.perfil_financiero import PerfilFinanciero
from app.models.evaluacion import Evaluacion
from app.models.amortizacion import CuotaAmortizacion
from app.models.pago import Pago
from app.models.audit_log import AuditLog
from app.models.notificacion import Notificacion


# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=test_engine
)

# Create all tables in the in‑memory database
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    """Yield a session bound to the test engine.

    This function replaces :func:`app.config.database.get_db` during tests.
    """
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Return a FastAPI TestClient that uses the overridden DB dependency."""
    # Override the dependency before creating the client
    app.dependency_overrides[prod_get_db] = override_get_db
    
    # Bypass para get_current_user y get_current_active_user para mantener compatibles los tests existentes
    from app.core.deps import get_current_user, get_current_active_user
    from app.models.usuario import Usuario
    from app.core.security import get_password_hash
    from app.models.cliente import Cliente
    
    db = TestSessionLocal()
    try:
        bypass_user = db.query(Usuario).filter(Usuario.email == "bypass_admin@credifresh.com").first()
        if not bypass_user:
            bypass_user = Usuario(
                email="bypass_admin@credifresh.com",
                password_hash=get_password_hash("password123"),
                rol="ADMIN",
                activo=True
            )
            db.add(bypass_user)
            db.commit()
            db.refresh(bypass_user)
            
            # Crear un cliente de bypass asociado para evitar fallos de IDOR en consultas de tests legados
            bypass_cliente = Cliente(
                nombre="Bypass Admin Cliente",
                cedula="7777777",
                telefono="3007777777",
                usuario_id=bypass_user.id
            )
            db.add(bypass_cliente)
            db.commit()
    finally:
        db.close()
    
    from fastapi import Depends
    from sqlalchemy.orm import Session
    from app.config.database import get_db
    
    def override_get_current_user(db: Session = Depends(get_db)):
        usuario = db.query(Usuario).filter(Usuario.email == "bypass_admin@credifresh.com").first()
        return usuario
        
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_current_active_user] = override_get_current_user
    
    with TestClient(app) as c:
        yield c
        
    # Clean up overrides after the session
    app.dependency_overrides.pop(prod_get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_active_user, None)


