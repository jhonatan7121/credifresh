import pytest
from fastapi.testclient import TestClient


def test_crear_cliente_exitoso(client: TestClient):
    """1. Crear cliente exitoso."""
    datos_cliente = {
        "nombre": "Juan Perez",
        "cedula": "1234567",
        "telefono": "3001234567"
    }
    response = client.post("/clientes/", json=datos_cliente)
    assert response.status_code == 201
    
    data = response.json()
    assert data["mensaje"] == "Cliente creado correctamente"
    assert data["cliente"]["nombre"] == datos_cliente["nombre"]
    assert data["cliente"]["cedula"] == datos_cliente["cedula"]
    assert data["cliente"]["telefono"] == datos_cliente["telefono"]
    assert "id" in data["cliente"]


def test_crear_cliente_cedula_duplicada(client: TestClient):
    """2. Cédula duplicada."""
    datos_cliente = {
        "nombre": "Juan Perez",
        "cedula": "12345678",
        "telefono": "3001234567"
    }
    # Primer registro
    response1 = client.post("/clientes/", json=datos_cliente)
    assert response1.status_code == 201

    # Segundo registro con la misma cédula
    response2 = client.post("/clientes/", json=datos_cliente)
    assert response2.status_code == 409
    assert response2.json()["detail"] == "La cédula ya está registrada"


def test_crear_cliente_datos_invalidos(client: TestClient):
    """3. Datos inválidos."""
    # Nombre muy corto (min_length=2)
    datos_nombre_corto = {
        "nombre": "A",
        "cedula": "123456",
        "telefono": "3001234567"
    }
    response = client.post("/clientes/", json=datos_nombre_corto)
    assert response.status_code == 422

    # Cédula con letras (pattern=r"^\d+$")
    datos_cedula_letras = {
        "nombre": "Juan Perez",
        "cedula": "12345A",
        "telefono": "3001234567"
    }
    response = client.post("/clientes/", json=datos_cedula_letras)
    assert response.status_code == 422

    # Teléfono inválido (pattern=r"^\+?\d+$")
    datos_telefono_invalido = {
        "nombre": "Juan Perez",
        "cedula": "123456",
        "telefono": "telefono12"
    }
    response = client.post("/clientes/", json=datos_telefono_invalido)
    assert response.status_code == 422


def test_obtener_cliente_exitosamente(client: TestClient):
    """4. Obtener cliente exitosamente."""
    datos_cliente = {
        "nombre": "Maria Gomez",
        "cedula": "9876543",
        "telefono": "3109876543"
    }
    create_response = client.post("/clientes/", json=datos_cliente)
    assert create_response.status_code == 201
    cliente_id = create_response.json()["cliente"]["id"]

    get_response = client.get(f"/clientes/{cliente_id}")
    assert get_response.status_code == 200
    data = get_response.json()
    assert data["nombre"] == datos_cliente["nombre"]
    assert data["cedula"] == datos_cliente["cedula"]
    assert data["id"] == cliente_id


def test_cliente_no_encontrado(client: TestClient):
    """5. Cliente no encontrado."""
    response = client.get("/clientes/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Cliente no encontrado"


def test_listar_clientes(client: TestClient):
    """6. Listar clientes."""
    # Primero obtenemos el estado inicial de clientes
    get_initial = client.get("/clientes/")
    assert get_initial.status_code == 200
    inicial_count = len(get_initial.json())

    # Creamos un par de clientes
    cliente1 = {"nombre": "Test Uno", "cedula": "111111", "telefono": "11111111"}
    cliente2 = {"nombre": "Test Dos", "cedula": "222222", "telefono": "22222222"}
    
    client.post("/clientes/", json=cliente1)
    client.post("/clientes/", json=cliente2)

    get_final = client.get("/clientes/")
    assert get_final.status_code == 200
    final_data = get_final.json()
    assert len(final_data) == inicial_count + 2
    
    cedulas = [c["cedula"] for c in final_data]
    assert "111111" in cedulas
    assert "222222" in cedulas


def test_actualizar_cliente_exitosamente(client: TestClient):
    """7. Actualizar cliente exitosamente."""
    datos_cliente = {
        "nombre": "Pedro Rojas",
        "cedula": "555555",
        "telefono": "3205555555"
    }
    create_response = client.post("/clientes/", json=datos_cliente)
    assert create_response.status_code == 201

    datos_actualizados = {
        "nombre": "Pedro Rojas Editado",
        "cedula": "555555",  # Misma cédula
        "telefono": "3209999999"
    }

    put_response = client.put("/clientes/555555", json=datos_actualizados)
    assert put_response.status_code == 200
    
    data = put_response.json()
    assert data["mensaje"] == "Cliente actualizado correctamente"
    assert data["cliente"]["nombre"] == datos_actualizados["nombre"]
    assert data["cliente"]["telefono"] == datos_actualizados["telefono"]


def test_actualizar_cliente_inexistente(client: TestClient):
    """8. Actualizar cliente inexistente."""
    datos_actualizados = {
        "nombre": "No Existo",
        "cedula": "999999",
        "telefono": "3000000000"
    }
    response = client.put("/clientes/000000", json=datos_actualizados)
    assert response.status_code == 404
    assert response.json()["detail"] == "Cliente no encontrado"


def test_actualizar_usando_cedula_duplicada(client: TestClient):
    """9. Actualizar usando una cédula duplicada."""
    # Creamos cliente A
    cliente_a = {"nombre": "Cliente A", "cedula": "888881", "telefono": "3111111111"}
    client.post("/clientes/", json=cliente_a)

    # Creamos cliente B
    cliente_b = {"nombre": "Cliente B", "cedula": "888882", "telefono": "3222222222"}
    client.post("/clientes/", json=cliente_b)

    # Intentamos actualizar cliente B poniéndole la cédula de cliente A (888881)
    datos_actualizados = {
        "nombre": "Cliente B Editado",
        "cedula": "888881",  # Cédula duplicada
        "telefono": "3222222222"
    }
    response = client.put("/clientes/888882", json=datos_actualizados)
    assert response.status_code == 409
    assert response.json()["detail"] == "La cédula ya está registrada"


def test_eliminar_cliente_exitosamente(client: TestClient):
    """10. Eliminar cliente exitosamente."""
    datos_cliente = {
        "nombre": "Eliminame",
        "cedula": "777777",
        "telefono": "3007777777"
    }
    client.post("/clientes/", json=datos_cliente)

    # Eliminar
    delete_response = client.delete("/clientes/777777")
    assert delete_response.status_code == 200
    
    data = delete_response.json()
    assert data["mensaje"] == "Cliente eliminado correctamente"
    assert data["cliente"]["cedula"] == "777777"

    # Verificar que ya no existe
    get_response = client.get(f"/clientes/{data['cliente']['id']}")
    assert get_response.status_code == 404


def test_eliminar_cliente_inexistente(client: TestClient):
    """11. Eliminar cliente inexistente."""
    response = client.delete("/clientes/000000")
    assert response.status_code == 404
    assert response.json()["detail"] == "Cliente no encontrado"


def test_intentar_eliminar_cliente_con_credito_asociado(client: TestClient):
    """12. Intentar eliminar cliente con crédito asociado."""
    # Creamos cliente
    datos_cliente = {
        "nombre": "Cliente Deudor",
        "cedula": "666666",
        "telefono": "3006666666"
    }
    create_response = client.post("/clientes/", json=datos_cliente)
    assert create_response.status_code == 201
    cliente_id = create_response.json()["cliente"]["id"]

    # Creamos un crédito asociado
    credito_data = {
        "cliente_id": cliente_id,
        "monto": 500000.0,
        "plazo_meses": 6,
        "tasa_interes": 2.5
    }
    credito_response = client.post("/creditos/", json=credito_data)
    assert credito_response.status_code == 201

    # Intentamos eliminar el cliente
    delete_response = client.delete("/clientes/666666")
    assert delete_response.status_code == 409
    assert delete_response.json()["detail"] == "No se puede eliminar un cliente con créditos asociados"
