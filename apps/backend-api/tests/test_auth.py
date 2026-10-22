import pytest
from uuid import uuid4
from fastapi.testclient import TestClient
from jose import jwt

from app.core.security import SECRET_KEY, ALGORITHM, get_password_hash
from app.models.usuario import Usuario
from conftest import TestSessionLocal


def test_registro_usuario_exitoso(client: TestClient):
    """Prueba de registro exitoso de usuario."""
    datos_registro = {
        "email": "nuevo_usuario@credifresh.com",
        "password": "PruebaSegura123",
        "rol": "CLIENTE"
    }
    response = client.post("/auth/register", json=datos_registro)
    assert response.status_code == 201
    
    data = response.json()
    assert "id" in data
    assert data["email"] == datos_registro["email"]
    assert data["rol"] == datos_registro["rol"]
    assert data["activo"] is True
    # Nunca se debe exponer el password_hash o la contraseña original
    assert "password" not in data
    assert "password_hash" not in data


def test_registro_email_duplicado(client: TestClient):
    """Prueba de registro con email duplicado devuelve HTTP 409."""
    email = "duplicado@credifresh.com"
    datos_registro1 = {
        "email": email,
        "password": "PruebaSegura123",
        "rol": "CLIENTE"
    }
    # Primer registro
    response1 = client.post("/auth/register", json=datos_registro1)
    assert response1.status_code == 201
    
    # Segundo registro con el mismo email
    datos_registro2 = {
        "email": email,
        "password": "PruebaSegura456",
        "rol": "CLIENTE"
    }
    response2 = client.post("/auth/register", json=datos_registro2)
    assert response2.status_code == 409
    assert response2.json()["detail"] == "El email ya está registrado"


def test_registro_datos_invalidos(client: TestClient):
    """Prueba de registro con datos inválidos (email mal formateado o clave corta) devuelve HTTP 422."""
    # Email inválido
    datos_email_invalido = {
        "email": "correo_invalido",
        "password": "PruebaSegura123",
        "rol": "CLIENTE"
    }
    response = client.post("/auth/register", json=datos_email_invalido)
    assert response.status_code == 422

    # Contraseña corta (menos de 12 caracteres)
    datos_clave_corta = {
        "email": "valido@credifresh.com",
        "password": "123",
        "rol": "CLIENTE"
    }
    response = client.post("/auth/register", json=datos_clave_corta)
    assert response.status_code == 422


def test_login_exitoso_y_jwt_valido(client: TestClient):
    """Prueba de login exitoso y verificación de generación válida del JWT."""
    email = "login_exitoso@credifresh.com"
    password = "PruebaSegura123"
    
    # Primero registrar el usuario
    datos_registro = {
        "email": email,
        "password": password,
        "rol": "CLIENTE"
    }
    client.post("/auth/register", json=datos_registro)
    
    # Intentar login
    datos_login = {
        "email": email,
        "password": password
    }
    response = client.post("/auth/login", json=datos_login)
    assert response.status_code == 200
    
    token_data = response.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"
    
    # Verificar validez del JWT decodificándolo
    token = token_data["access_token"]
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    
    assert payload["sub"] == email
    assert payload["rol"] == "CLIENTE"
    assert "exp" in payload


def test_login_contrasena_incorrecta(client: TestClient):
    """Prueba de login con contraseña incorrecta devuelve HTTP 401."""
    email = "error_clave@credifresh.com"
    password = "PruebaSegura123"
    
    # Registrar el usuario
    datos_registro = {
        "email": email,
        "password": password,
        "rol": "CLIENTE"
    }
    client.post("/auth/register", json=datos_registro)
    
    # Intentar login con clave incorrecta
    datos_login = {
        "email": email,
        "password": "clave_incorrecta"
    }
    response = client.post("/auth/login", json=datos_login)
    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciales incorrectas"


def test_login_usuario_inexistente(client: TestClient):
    """Prueba de login con usuario inexistente devuelve HTTP 401."""
    datos_login = {
        "email": "inexistente@credifresh.com",
        "password": "PruebaSegura123"
    }
    response = client.post("/auth/login", json=datos_login)
    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciales incorrectas"


def test_login_usuario_inactivo(client: TestClient):
    """Prueba de login con usuario inactivo."""
    email = "inactivo@credifresh.com"
    password = "PruebaSegura123"
    
    # Registrar el usuario
    datos_registro = {
        "email": email,
        "password": password,
        "rol": "CLIENTE"
    }
    reg_response = client.post("/auth/register", json=datos_registro)
    assert reg_response.status_code == 201, f"Registro falló: {reg_response.text}"

    
    # Cambiar estado del usuario a inactivo directamente en la base de datos de pruebas
    from main import app
    from app.config.database import get_db as prod_get_db
    
    db_generator = app.dependency_overrides[prod_get_db]()
    db = next(db_generator)
    try:
        usuario = db.query(Usuario).filter(Usuario.email == email).first()
        assert usuario is not None
        usuario.activo = False
        db.commit()
    finally:
        try:
            next(db_generator)
        except StopIteration:
            pass
        
    # Intentar login con el usuario ahora inactivo
    datos_login = {
        "email": email,
        "password": password
    }
    response = client.post("/auth/login", json=datos_login)
    # Debe devolver un error controlado (por ejemplo, 400 Bad Request)
    assert response.status_code == 400
    assert response.json()["detail"] == "El usuario está inactivo"


def test_login_aplica_limite_por_cuenta(client: TestClient):
    email = f"limite-{uuid4().hex}@credifresh.test"
    payload = {"email": email, "password": "clave-fallida"}
    for _ in range(10):
        assert client.post("/auth/login", json=payload).status_code == 401

    response = client.post("/auth/login", json=payload)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_registro_exige_12_caracteres(client: TestClient):
    response = client.post(
        "/auth/register",
        json={"email": f"password-corta-{uuid4().hex}@credifresh.test", "password": "12345678901"},
    )
    assert response.status_code == 422


def test_login_mantiene_compatibilidad_con_cuenta_existente(client: TestClient):
    email = f"cuenta-anterior-{uuid4().hex}@credifresh.test"
    password = "oldpwd"
    db = TestSessionLocal()
    try:
        db.add(Usuario(email=email, password_hash=get_password_hash(password), rol="CLIENTE", activo=True))
        db.commit()
    finally:
        db.close()

    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200


def test_password_reset_limita_solicitudes_sin_enviar_correo(client: TestClient, monkeypatch):
    for name in ("SMTP_HOST", "SMTP_FROM_EMAIL", "SMTP_USERNAME", "SMTP_PASSWORD", "RESET_PASSWORD_URL"):
        monkeypatch.delenv(name, raising=False)
    email = f"reset-limite-{uuid4().hex}@credifresh.test"

    for _ in range(3):
        response = client.post("/auth/password-reset/request", json={"email": email})
        assert response.status_code == 503

    response = client.post("/auth/password-reset/request", json={"email": email})
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
