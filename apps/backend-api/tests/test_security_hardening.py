import os
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


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

    importlib.reload(app.core.security)
    with pytest.raises(RuntimeError, match="No se permite utilizar wildcard"):
        importlib.reload(main)

    # Limpiar entorno de prueba
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    importlib.reload(main)
    importlib.reload(app.core.security)
