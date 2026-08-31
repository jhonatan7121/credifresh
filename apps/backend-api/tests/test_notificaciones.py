import pytest
from fastapi.testclient import TestClient
from conftest import TestSessionLocal
from app.models.notificacion import Notificacion
from app.models.usuario import Usuario
from app.models.cliente import Cliente

_ced_notif = 9500000

def generar_datos_cliente_notif():
    global _ced_notif
    _ced_notif += 1
    return {
        "nombre": f"Cliente Notif {_ced_notif}",
        "cedula": str(_ced_notif),
        "telefono": "3120000000"
    }


def registrar_usuario_y_cliente(client: TestClient, email: str, rol: str = "CLIENTE"):
    reg_resp = client.post("/auth/register", json={
        "email": email,
        "password": "password123",
        "rol": rol
    })
    assert reg_resp.status_code == 201
    usuario_id = reg_resp.json()["id"]

    login_resp = client.post("/auth/login", json={
        "email": email,
        "password": "password123"
    })
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    if rol == "CLIENTE":
        cli_data = generar_datos_cliente_notif()
        cli_resp = client.post("/clientes/", json=cli_data)
        assert cli_resp.status_code == 201
        cliente_id = cli_resp.json()["cliente"]["id"]

        db = TestSessionLocal()
        try:
            cli_db = db.query(Cliente).filter(Cliente.id == cliente_id).first()
            cli_db.usuario_id = usuario_id
            db.commit()
        finally:
            db.close()
    else:
        cliente_id = None

    return {"usuario_id": usuario_id, "token": token, "cliente_id": cliente_id}


def test_notificacion_creacion_solicitud(client: TestClient):
    """1. Creación de notificación por solicitud de crédito cuando existe usuario."""
    user_info = registrar_usuario_y_cliente(client, "solicitudnotif@credifresh.com")
    headers = {"Authorization": f"Bearer {user_info['token']}"}

    client.post(f"/clientes/{user_info['cliente_id']}/perfil-financiero", json={
        "ingresos_mensuales": 4000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    }, headers=headers)

    cred_resp = client.post("/creditos/", json={
        "cliente_id": user_info['cliente_id'],
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    }, headers=headers)
    assert cred_resp.status_code == 201

    notif_resp = client.get("/notificaciones/", headers=headers)
    assert notif_resp.status_code == 200
    data = notif_resp.json()
    assert len(data) >= 1
    assert "solicitud" in data[0]["titulo"].lower()


def test_notificacion_aprobacion(client: TestClient):
    """2. Notificación por aprobación."""
    user_info = registrar_usuario_y_cliente(client, "aprobacionnotif@credifresh.com")
    headers_client = {"Authorization": f"Bearer {user_info['token']}"}

    client.post(f"/clientes/{user_info['cliente_id']}/perfil-financiero", json={
        "ingresos_mensuales": 4000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    }, headers=headers_client)

    cred_resp = client.post("/creditos/", json={
        "cliente_id": user_info['cliente_id'],
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    }, headers=headers_client)
    credito_id = cred_resp.json()["credito"]["id"]

    eval_resp = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp.status_code == 200
    assert eval_resp.json()["decision"] == "APROBADO"

    notif_resp = client.get("/notificaciones/", headers=headers_client)
    assert notif_resp.status_code == 200
    data = notif_resp.json()
    titulos = [n["titulo"] for n in data]
    assert "Crédito aprobado" in titulos


def test_notificacion_desembolso(client: TestClient):
    """4. Notificación por desembolso."""
    user_info = registrar_usuario_y_cliente(client, "desembolsonotif@credifresh.com")
    headers_client = {"Authorization": f"Bearer {user_info['token']}"}

    client.post(f"/clientes/{user_info['cliente_id']}/perfil-financiero", json={
        "ingresos_mensuales": 4000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    }, headers=headers_client)

    cred_resp = client.post("/creditos/", json={
        "cliente_id": user_info['cliente_id'],
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    }, headers=headers_client)
    credito_id = cred_resp.json()["credito"]["id"]

    client.post(f"/creditos/{credito_id}/evaluar")
    desem_resp = client.post(f"/creditos/{credito_id}/desembolsar")
    assert desem_resp.status_code == 200

    notif_resp = client.get("/notificaciones/", headers=headers_client)
    assert notif_resp.status_code == 200
    titulos = [n["titulo"] for n in notif_resp.json()]
    assert "Crédito desembolsado" in titulos


def test_cliente_consulta_propias_y_idor(client: TestClient):
    """5. Cliente consulta sus propias notificaciones y 6. NO puede consultar notificaciones de otro."""
    user1 = registrar_usuario_y_cliente(client, "cli1notif@credifresh.com")
    user2 = registrar_usuario_y_cliente(client, "cli2notif@credifresh.com")

    headers1 = {"Authorization": f"Bearer {user1['token']}"}
    headers2 = {"Authorization": f"Bearer {user2['token']}"}

    client.post(f"/clientes/{user1['cliente_id']}/perfil-financiero", json={
        "ingresos_mensuales": 4000000.0, "gastos_mensuales": 1000000.0, "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado", "actividad_economica": "Analista"
    }, headers=headers1)
    client.post("/creditos/", json={
        "cliente_id": user1['cliente_id'], "monto": 1000000.0, "plazo_meses": 10, "tasa_interes": 2.0
    }, headers=headers1)

    from main import app
    from app.core.deps import get_current_user, get_current_active_user
    old_user = app.dependency_overrides.pop(get_current_user, None)
    old_active = app.dependency_overrides.pop(get_current_active_user, None)

    try:
        resp2 = client.get("/notificaciones/", headers=headers2)
        assert resp2.status_code == 200
        assert len(resp2.json()) == 0
    finally:
        if old_user:
            app.dependency_overrides[get_current_user] = old_user
        if old_active:
            app.dependency_overrides[get_current_active_user] = old_active


def test_marcar_notificacion_leida_y_idor(client: TestClient):
    """7. Cliente marca propia leída y 8. NO puede marcar ajena."""
    user1 = registrar_usuario_y_cliente(client, "cli1leer@credifresh.com")
    user2 = registrar_usuario_y_cliente(client, "cli2leer@credifresh.com")

    headers1 = {"Authorization": f"Bearer {user1['token']}"}
    headers2 = {"Authorization": f"Bearer {user2['token']}"}

    client.post(f"/clientes/{user1['cliente_id']}/perfil-financiero", json={
        "ingresos_mensuales": 4000000.0, "gastos_mensuales": 1000000.0, "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado", "actividad_economica": "Analista"
    }, headers=headers1)
    client.post("/creditos/", json={
        "cliente_id": user1['cliente_id'], "monto": 1000000.0, "plazo_meses": 10, "tasa_interes": 2.0
    }, headers=headers1)

    from main import app
    from app.core.deps import get_current_user, get_current_active_user
    old_user = app.dependency_overrides.pop(get_current_user, None)
    old_active = app.dependency_overrides.pop(get_current_active_user, None)

    try:
        notifs = client.get("/notificaciones/", headers=headers1).json()
        notif_id = notifs[0]["id"]

        patch_resp = client.patch(f"/notificaciones/{notif_id}/leer", headers=headers2)
        assert patch_resp.status_code == 403

        patch_resp1 = client.patch(f"/notificaciones/{notif_id}/leer", headers=headers1)
        assert patch_resp1.status_code == 200
        assert patch_resp1.json()["leida"] is True
    finally:
        if old_user:
            app.dependency_overrides[get_current_user] = old_user
        if old_active:
            app.dependency_overrides[get_current_active_user] = old_active


def test_notificacion_sin_auth_401(client: TestClient):
    """9. Solicitud sin autenticación devuelve 401."""
    from main import app
    from app.core.deps import get_current_user, get_current_active_user
    old_user = app.dependency_overrides.pop(get_current_user, None)
    old_active = app.dependency_overrides.pop(get_current_active_user, None)

    try:
        resp = client.get("/notificaciones/")
        assert resp.status_code == 401
    finally:
        if old_user:
            app.dependency_overrides[get_current_user] = old_user
        if old_active:
            app.dependency_overrides[get_current_active_user] = old_active


def test_cliente_sin_usuario_asociado_no_rompe(client: TestClient):
    """11. Cliente sin usuario asociado no rompe la operación financiera."""
    cli_resp = client.post("/clientes/", json={
        "nombre": "Cliente Sin Usuario",
        "cedula": "88888899",
        "telefono": "3000000000"
    })
    assert cli_resp.status_code == 201
    cliente_id = cli_resp.json()["cliente"]["id"]

    client.post(f"/clientes/{cliente_id}/perfil-financiero", json={
        "ingresos_mensuales": 4000000.0, "gastos_mensuales": 1000000.0, "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado", "actividad_economica": "Analista"
    })

    cred_resp = client.post("/creditos/", json={
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    })
    assert cred_resp.status_code == 201
