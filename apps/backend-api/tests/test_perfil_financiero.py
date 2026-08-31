import pytest
from fastapi.testclient import TestClient


def test_crear_perfil_financiero_exitoso(client: TestClient):
    """1. Crear perfil financiero exitoso."""
    # Creamos un cliente primero
    datos_cliente = {
        "nombre": "Andres Felipe",
        "cedula": "998877",
        "telefono": "3159988770"
    }
    create_cliente_resp = client.post("/clientes/", json=datos_cliente)
    assert create_cliente_resp.status_code == 201
    cliente_id = create_cliente_resp.json()["cliente"]["id"]

    # Creamos el perfil financiero
    perfil_data = {
        "ingresos_mensuales": 1500000.0,
        "gastos_mensuales": 500000.0,
        "otras_obligaciones": 100000.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    }
    response = client.post(f"/clientes/{cliente_id}/perfil-financiero", json=perfil_data)
    assert response.status_code == 201
    
    data = response.json()
    assert data["mensaje"] == "Perfil financiero creado correctamente"
    assert data["perfil_financiero"]["cliente_id"] == cliente_id
    assert data["perfil_financiero"]["ingresos_mensuales"] == perfil_data["ingresos_mensuales"]
    assert data["perfil_financiero"]["gastos_mensuales"] == perfil_data["gastos_mensuales"]
    assert data["perfil_financiero"]["otras_obligaciones"] == perfil_data["otras_obligaciones"]
    assert data["perfil_financiero"]["tipo_ingresos"] == perfil_data["tipo_ingresos"]
    assert data["perfil_financiero"]["actividad_economica"] == perfil_data["actividad_economica"]


def test_crear_perfil_financiero_cliente_inexistente(client: TestClient):
    """2. Crear perfil financiero para cliente inexistente."""
    perfil_data = {
        "ingresos_mensuales": 1500000.0,
        "gastos_mensuales": 500000.0,
        "otras_obligaciones": 100000.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    }
    response = client.post("/clientes/999999/perfil-financiero", json=perfil_data)
    assert response.status_code == 404
    assert response.json()["detail"] == "Cliente no encontrado"


def test_crear_perfil_financiero_duplicado(client: TestClient):
    """3. Crear perfil financiero duplicado para el mismo cliente."""
    # Crear cliente
    datos_cliente = {
        "nombre": "Andres Duplicado",
        "cedula": "998878",
        "telefono": "3159988771"
    }
    create_cliente_resp = client.post("/clientes/", json=datos_cliente)
    assert create_cliente_resp.status_code == 201
    cliente_id = create_cliente_resp.json()["cliente"]["id"]

    # Crear primer perfil financiero
    perfil_data = {
        "ingresos_mensuales": 1500000.0,
        "gastos_mensuales": 500000.0,
        "otras_obligaciones": 100000.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    }
    resp1 = client.post(f"/clientes/{cliente_id}/perfil-financiero", json=perfil_data)
    assert resp1.status_code == 201

    # Intentar crear segundo perfil financiero para el mismo cliente
    resp2 = client.post(f"/clientes/{cliente_id}/perfil-financiero", json=perfil_data)
    assert resp2.status_code == 409
    assert resp2.json()["detail"] == "El cliente ya tiene un perfil financiero"


def test_crear_perfil_financiero_ingresos_invalidos(client: TestClient):
    """4. Crear perfil financiero con ingresos inválidos (<= 0)."""
    # Ingresos mensuales de 0
    perfil_data_cero = {
        "ingresos_mensuales": 0.0,
        "gastos_mensuales": 500000.0,
        "otras_obligaciones": 100000.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    }
    response_cero = client.post("/clientes/1/perfil-financiero", json=perfil_data_cero)
    assert response_cero.status_code == 422

    # Ingresos mensuales negativos
    perfil_data_negativo = {
        "ingresos_mensuales": -100.0,
        "gastos_mensuales": 500000.0,
        "otras_obligaciones": 100000.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    }
    response_negativo = client.post("/clientes/1/perfil-financiero", json=perfil_data_negativo)
    assert response_negativo.status_code == 422


def test_crear_perfil_financiero_gastos_u_obligaciones_negativos(client: TestClient):
    """5. Crear perfil financiero con gastos u obligaciones negativos."""
    # Gastos negativos
    perfil_gastos_negativos = {
        "ingresos_mensuales": 1500000.0,
        "gastos_mensuales": -50000.0,
        "otras_obligaciones": 100000.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    }
    response_gastos = client.post("/clientes/1/perfil-financiero", json=perfil_gastos_negativos)
    assert response_gastos.status_code == 422

    # Obligaciones negativas
    perfil_obligaciones_negativas = {
        "ingresos_mensuales": 1500000.0,
        "gastos_mensuales": 500000.0,
        "otras_obligaciones": -100.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    }
    response_obligaciones = client.post("/clientes/1/perfil-financiero", json=perfil_obligaciones_negativas)
    assert response_obligaciones.status_code == 422


def test_crear_perfil_financiero_campos_texto_invalidos(client: TestClient):
    """6. Crear perfil financiero con campos de texto inválidos (< 2 caracteres)."""
    # tipo_ingresos muy corto
    perfil_tipo_corto = {
        "ingresos_mensuales": 1500000.0,
        "gastos_mensuales": 500000.0,
        "otras_obligaciones": 100000.0,
        "tipo_ingresos": "E",
        "actividad_economica": "Analista"
    }
    response_tipo = client.post("/clientes/1/perfil-financiero", json=perfil_tipo_corto)
    assert response_tipo.status_code == 422

    # actividad_economica muy corta
    perfil_actividad_corta = {
        "ingresos_mensuales": 1500000.0,
        "gastos_mensuales": 500000.0,
        "otras_obligaciones": 100000.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "A"
    }
    response_actividad = client.post("/clientes/1/perfil-financiero", json=perfil_actividad_corta)
    assert response_actividad.status_code == 422


def test_obtener_perfil_financiero_exitoso(client: TestClient):
    """7. Obtener perfil financiero exitoso."""
    # Creamos un cliente
    datos_cliente = {
        "nombre": "Camilo Torres",
        "cedula": "998879",
        "telefono": "3159988772"
    }
    create_cliente_resp = client.post("/clientes/", json=datos_cliente)
    assert create_cliente_resp.status_code == 201
    cliente_id = create_cliente_resp.json()["cliente"]["id"]

    # Creamos el perfil financiero
    perfil_data = {
        "ingresos_mensuales": 2000000.0,
        "gastos_mensuales": 600000.0,
        "otras_obligaciones": 200000.0,
        "tipo_ingresos": "Independiente",
        "actividad_economica": "Comerciante"
    }
    create_perfil_resp = client.post(f"/clientes/{cliente_id}/perfil-financiero", json=perfil_data)
    assert create_perfil_resp.status_code == 201

    # Obtener el perfil
    get_response = client.get(f"/clientes/{cliente_id}/perfil-financiero")
    assert get_response.status_code == 200
    
    data = get_response.json()
    assert data["cliente_id"] == cliente_id
    assert data["ingresos_mensuales"] == perfil_data["ingresos_mensuales"]
    assert data["gastos_mensuales"] == perfil_data["gastos_mensuales"]
    assert data["otras_obligaciones"] == perfil_data["otras_obligaciones"]
    assert data["tipo_ingresos"] == perfil_data["tipo_ingresos"]
    assert data["actividad_economica"] == perfil_data["actividad_economica"]


def test_obtener_perfil_financiero_cliente_inexistente(client: TestClient):
    """8. Obtener perfil financiero de un cliente inexistente."""
    response = client.get("/clientes/999999/perfil-financiero")
    assert response.status_code == 404
    assert response.json()["detail"] == "Cliente no encontrado"


def test_obtener_perfil_financiero_no_creado(client: TestClient):
    """9. Obtener perfil financiero no creado para cliente existente."""
    # Crear cliente sin perfil
    datos_cliente = {
        "nombre": "Sin Perfil",
        "cedula": "998880",
        "telefono": "3159988773"
    }
    create_cliente_resp = client.post("/clientes/", json=datos_cliente)
    assert create_cliente_resp.status_code == 201
    cliente_id = create_cliente_resp.json()["cliente"]["id"]

    # Obtener perfil
    response = client.get(f"/clientes/{cliente_id}/perfil-financiero")
    assert response.status_code == 404
    assert response.json()["detail"] == "Perfil financiero no encontrado"
