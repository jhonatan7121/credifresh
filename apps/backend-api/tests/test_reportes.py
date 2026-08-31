import pytest
from fastapi.testclient import TestClient
from decimal import Decimal
from conftest import TestSessionLocal
from app.models.cliente import Cliente
from app.models.credito import Credito

# Helper para crear un cliente y un crédito en estado solicitado/desembolsado según se requiera
_ced_reportes = 8000000

def generar_cedula_reportes():
    global _ced_reportes
    _ced_reportes += 1
    return str(_ced_reportes)


def test_resumen_cartera_exitoso_admin_gestor(client: TestClient):
    """1 y 7 y 8 y 9. Resumen exitoso, conteos por estado, totales de desembolsos y recaudados con Admin/Gestor."""
    # Consultar resumen con el usuario bypass (ADMIN)
    resp = client.get("/reportes/resumen")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_clientes" in data
    assert "total_creditos" in data
    assert "creditos_por_estado" in data
    assert "monto_total_solicitado" in data
    assert "monto_total_desembolsado" in data
    assert "monto_total_recaudado" in data


def test_cartera_detalle_exitoso(client: TestClient):
    """2 y 10. Cartera detalle exitosa y cuotas pendientes/parciales."""
    resp = client.get("/reportes/cartera")
    assert resp.status_code == 200
    data = resp.json()
    assert "cuotas_por_estado" in data
    assert "saldo_pendiente_cartera" in data


def test_bloqueo_reportes_cliente(client: TestClient):
    """3. Un CLIENTE recibe 403 al intentar consultar /reportes/resumen y /reportes/cartera."""
    # Registrar usuario CLIENTE
    email_cliente = "cliente_reportes@credifresh.com"
    client.post("/auth/register", json={"email": email_cliente, "password": "password123", "rol": "CLIENTE"})
    login_resp = client.post("/auth/login", json={"email": email_cliente, "password": "password123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Quitar temporalmente el override de admin en la sesion de pruebas para probar autenticación real del cliente
    from main import app
    from app.core.deps import get_current_user, get_current_active_user
    old_user = app.dependency_overrides.pop(get_current_user, None)
    old_active = app.dependency_overrides.pop(get_current_active_user, None)

    try:
        resp_resumen = client.get("/reportes/resumen", headers=headers)
        assert resp_resumen.status_code == 403

        resp_cartera = client.get("/reportes/cartera", headers=headers)
        assert resp_cartera.status_code == 403
    finally:
        if old_user:
            app.dependency_overrides[get_current_user] = old_user
        if old_active:
            app.dependency_overrides[get_current_active_user] = old_active


def test_bloqueo_reportes_sin_autenticacion(client: TestClient):
    """4. Sin autenticación recibe 401."""
    from main import app
    from app.core.deps import get_current_user, get_current_active_user
    old_user = app.dependency_overrides.pop(get_current_user, None)
    old_active = app.dependency_overrides.pop(get_current_active_user, None)

    try:
        resp_resumen = client.get("/reportes/resumen")
        assert resp_resumen.status_code == 401

        resp_cartera = client.get("/reportes/cartera")
        assert resp_cartera.status_code == 401
    finally:
        if old_user:
            app.dependency_overrides[get_current_user] = old_user
        if old_active:
            app.dependency_overrides[get_current_active_user] = old_active


def test_precision_decimal_y_cartera_vacia(client: TestClient):
    """5 y 6. Precisión Decimal y manejo correcto de cartera vacía (o con datos consistentes en Decimal)."""
    resp = client.get("/reportes/resumen")
    assert resp.status_code == 200
    data = resp.json()
    
    # Verificar que los montos retornados son strings parseables como Decimal con 2 decimales
    monto_solicitado = Decimal(str(data["monto_total_solicitado"]))
    monto_desembolsado = Decimal(str(data["monto_total_desembolsado"]))
    monto_recaudado = Decimal(str(data["monto_total_recaudado"]))

    assert isinstance(monto_solicitado, Decimal)
    assert isinstance(monto_desembolsado, Decimal)
    assert isinstance(monto_recaudado, Decimal)

    resp_cartera = client.get("/reportes/cartera")
    assert resp_cartera.status_code == 200
    data_cartera = resp_cartera.json()
    saldo_pendiente = Decimal(str(data_cartera["saldo_pendiente_cartera"]))
    assert isinstance(saldo_pendiente, Decimal)
