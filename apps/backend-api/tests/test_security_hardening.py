import os
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@pytest.fixture(autouse=True)
def restore_security_module_state():
    """Evita que los reload de security.py contaminen otros tests con SECRET_KEY."""
    import app.core.security as security

    original_state = {
        "SECRET_KEY": security.SECRET_KEY,
        "ALGORITHM": security.ALGORITHM,
        "ACCESS_TOKEN_EXPIRE_MINUTES": security.ACCESS_TOKEN_EXPIRE_MINUTES,
    }
    yield
    for name, value in original_state.items():
        setattr(security, name, value)


def test_secret_key_missing_raises_error(monkeypatch):
    """Verificar que la aplicación falla al iniciar si SECRET_KEY no está definida."""
    monkeypatch.delenv("SECRET_KEY", raising=False)

    # Recargar o reimportar app/security para forzar la validación
    import importlib
    import app.core.security

    with pytest.raises(RuntimeError, match="SECRET_KEY no está configurada"):
        importlib.reload(app.core.security)


def test_cors_wildcard_in_production_raises_error(monkeypatch):
    """Verificar que CORS rechaza wildcard (*) en entorno de producción."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-123")

    import importlib
    import main
    import app.core.security

    # Guardar la aplicación original utilizada por los fixtures de pytest
    app_original = main.app

    importlib.reload(app.core.security)

    with pytest.raises(RuntimeError, match="No se permite utilizar wildcard"):
        importlib.reload(main)

    # Restaurar la aplicación original
    main.app = app_original

    # Limpiar entorno de prueba
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")

    importlib.reload(app.core.security)