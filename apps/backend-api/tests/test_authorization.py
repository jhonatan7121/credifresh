import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.usuario import Usuario
from app.models.cliente import Cliente
from app.core.security import get_password_hash
from main import app
from app.config.database import get_db as prod_get_db

def get_test_db() -> Session:
    db_generator = app.dependency_overrides[prod_get_db]()
    return next(db_generator)
@pytest.fixture(autouse=True)
def clean_auth_overrides():
    from app.core.deps import get_current_user, get_current_active_user
    old_current_user = app.dependency_overrides.get(get_current_user)
    old_active_user = app.dependency_overrides.get(get_current_active_user)
    
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_active_user, None)
    
    yield
    
    if old_current_user:
        app.dependency_overrides[get_current_user] = old_current_user
    if old_active_user:
        app.dependency_overrides[get_current_active_user] = old_active_user


def create_test_user(db: Session, email: str, password: str, rol: str) -> Usuario:
    hashed_password = get_password_hash(password)
    user = Usuario(email=email, password_hash=hashed_password, rol=rol, activo=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def get_token(client: TestClient, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]

def test_registro_no_permite_escalar_a_admin(client: TestClient):
    response = client.post("/auth/register", json={
        "email": "intento_admin@credifresh.com", "password": "password123", "rol": "ADMIN"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["rol"] == "CLIENTE"
    assert "password" not in data
    assert "password_hash" not in data

def test_registro_no_permite_escalar_a_gestor(client: TestClient):
    response = client.post("/auth/register", json={
        "email": "intento_gestor@credifresh.com", "password": "password123", "rol": "GESTOR"
    })
    assert response.status_code == 201
    assert response.json()["rol"] == "CLIENTE"

def test_endpoints_protegidos_sin_jwt(client: TestClient):
    assert client.get("/clientes/").status_code == 401
    assert client.get("/clientes/1").status_code == 401
    assert client.post("/clientes/", json={}).status_code == 401
    assert client.get("/creditos/").status_code == 401
    assert client.get("/creditos/1").status_code == 401
    assert client.post("/creditos/", json={}).status_code == 401

def test_cliente_no_puede_listar_clientes(client: TestClient):
    db = get_test_db()
    try:
        user = create_test_user(db, "cliente_listar@credifresh.com", "password123", "CLIENTE")
    finally:
        db.close()
    token = get_token(client, "cliente_listar@credifresh.com", "password123")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/clientes/", headers=headers)
    assert response.status_code == 403

def test_cliente_no_puede_cambiar_estado_o_evaluar_credito(client: TestClient):
    db = get_test_db()
    try:
        user = create_test_user(db, "cliente_creditos@credifresh.com", "password123", "CLIENTE")
    finally:
        db.close()
    token = get_token(client, "cliente_creditos@credifresh.com", "password123")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.patch("/creditos/1/estado", json={"estado": "APROBADO"}, headers=headers).status_code == 403
    assert client.post("/creditos/1/evaluar", headers=headers).status_code == 403

def test_cliente_acceso_recursos_propios_vs_ajenos(client: TestClient):
    db = get_test_db()
    try:
        user1 = create_test_user(db, "cliente1@credifresh.com", "password123", "CLIENTE")
        c1 = Cliente(nombre="Cliente Uno", cedula="11111199", telefono="3000000001", usuario_id=user1.id)
        db.add(c1)
        db.commit()
        db.refresh(c1)
        user2 = create_test_user(db, "cliente2@credifresh.com", "password123", "CLIENTE")
        c2 = Cliente(nombre="Cliente Dos", cedula="22222299", telefono="3000000002", usuario_id=user2.id)
        db.add(c2)
        db.commit()
        db.refresh(c2)
        c1_id = c1.id
        c2_id = c2.id
    finally:
        db.close()
    token1 = get_token(client, "cliente1@credifresh.com", "password123")
    headers1 = {"Authorization": f"Bearer {token1}"}
    resp_propio = client.get(f"/clientes/{c1_id}", headers=headers1)
    assert resp_propio.status_code == 200
    assert resp_propio.json()["nombre"] == "Cliente Uno"
    assert "password_hash" not in resp_propio.json()
    resp_ajeno = client.get(f"/clientes/{c2_id}", headers=headers1)
    assert resp_ajeno.status_code == 403

def test_gestor_permisos_y_restricciones(client: TestClient):
    db = get_test_db()
    try:
        gestor = create_test_user(db, "gestor@credifresh.com", "password123", "GESTOR")
    finally:
        db.close()
    token = get_token(client, "gestor@credifresh.com", "password123")
    headers = {"Authorization": f"Bearer {token}"}
    resp_list = client.get("/clientes/", headers=headers)
    assert resp_list.status_code == 200
    resp_create = client.post("/clientes/", json={
        "nombre": "Cliente Gestor", "cedula": "999999", "telefono": "3009999999"
    }, headers=headers)
    assert resp_create.status_code == 201
    cedula = resp_create.json()["cliente"]["cedula"]
    resp_delete = client.delete(f"/clientes/{cedula}", headers=headers)
    assert resp_delete.status_code == 403

def test_admin_permisos(client: TestClient):
    db = get_test_db()
    try:
        admin = create_test_user(db, "admin@credifresh.com", "password123", "ADMIN")
    finally:
        db.close()
    token = get_token(client, "admin@credifresh.com", "password123")
    headers = {"Authorization": f"Bearer {token}"}
    token_gestor = get_token(client, "gestor@credifresh.com", "password123")
    headers_gestor = {"Authorization": f"Bearer {token_gestor}"}
    resp_create = client.post("/clientes/", json={
        "nombre": "Cliente Admin Borrar", "cedula": "888888", "telefono": "3008888888"
    }, headers=headers_gestor)
    assert resp_create.status_code == 201
    cedula = resp_create.json()["cliente"]["cedula"]
    resp_delete = client.delete(f"/clientes/{cedula}", headers=headers)
    assert resp_delete.status_code == 200
    assert resp_delete.json()["mensaje"] == "Cliente eliminado correctamente"

