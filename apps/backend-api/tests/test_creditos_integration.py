import pytest
from fastapi.testclient import TestClient

# Helper para generar un cliente nuevo y evitar colisiones de cédula
_cedula_counter = 1234500

def generar_datos_cliente():
    global _cedula_counter
    _cedula_counter += 1
    return {
        "nombre": f"Cliente de Prueba {_cedula_counter}",
        "cedula": str(_cedula_counter),
        "telefono": "3001234567"
    }


def test_creacion_y_evaluacion_exitosa(client: TestClient):
    """1. Creación y evaluación exitosa de un crédito."""
    # Crear cliente
    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    # Crear perfil financiero con excelente capacidad
    perfil_data = {
        "ingresos_mensuales": 2000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 200000.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Desarrollador"
    }
    perfil_resp = client.post(f"/clientes/{cliente_id}/perfil-financiero", json=perfil_data)
    assert perfil_resp.status_code == 201

    # Crear crédito
    credito_data = {
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 201
    credito_id = credito_resp.json()["credito"]["id"]

    # Evaluar crédito
    eval_resp = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp.status_code == 200
    
    data = eval_resp.json()
    assert data["decision"] == "APROBADO"
    assert "El crédito cumple las reglas básicas de evaluación" in data["motivos"]


def test_rechazo_monto_superior_maximo(client: TestClient):
    """2. Bloqueo preventivo por monto superior a $1.500.000 en la creación."""
    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    # Crédito de 1.600.000 (superior al límite de 1.500.000)
    credito_data = {
        "cliente_id": cliente_id,
        "monto": 1600000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 400
    assert "El monto solicitado debe estar entre $500.000 y $1.500.000 COP" in credito_resp.json()["detail"]


def test_bloqueo_monto_inferior_minimo(client: TestClient):
    """Prueba bloqueo preventivo por monto inferior a $500.000 COP en la creación."""
    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    # Crédito de 400.000 (inferior al límite de 500.000)
    credito_data = {
        "cliente_id": cliente_id,
        "monto": 400000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 400
    assert "El monto solicitado debe estar entre $500.000 y $1.500.000 COP" in credito_resp.json()["detail"]


def test_rechazo_plazo_superior_maximo(client: TestClient):
    """3. Bloqueo preventivo por plazo superior a 12 meses en la creación."""
    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    # Plazo de 13 meses (superior al límite de 12 meses)
    credito_data = {
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 13,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 400
    assert "El plazo máximo es de 12 meses" in credito_resp.json()["detail"]


def test_rechazo_cuota_superior_capacidad(client: TestClient):
    """4. Rechazo por cuota superior al 40% de capacidad."""
    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    # Capacidad = 300000 - 100000 - 50000 = 150000. El 40% es 60000.
    perfil_data = {
        "ingresos_mensuales": 300000.0,
        "gastos_mensuales": 100000.0,
        "otras_obligaciones": 50000.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Auxiliar"
    }
    perfil_resp = client.post(f"/clientes/{cliente_id}/perfil-financiero", json=perfil_data)
    assert perfil_resp.status_code == 201

    # Cuota calculada para 1.000.000 a 10 meses al 2.0% es de 111.326,53.
    # Supera los 60.000 permitidos.
    credito_data = {
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 201
    credito_id = credito_resp.json()["credito"]["id"]

    eval_resp = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp.status_code == 200
    
    data = eval_resp.json()
    assert data["decision"] == "RECHAZADO"
    assert "La cuota mensual supera el 40% de la capacidad financiera disponible" in data["motivos"]


def test_rechazo_capacidad_financiera_menor_o_igual_cero(client: TestClient):
    """5. Rechazo por capacidad financiera <= 0."""
    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    # Capacidad = 500000 - 400000 - 150000 = -50000 (menor o igual a cero)
    perfil_data = {
        "ingresos_mensuales": 500000.0,
        "gastos_mensuales": 400000.0,
        "otras_obligaciones": 150000.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Auxiliar"
    }
    perfil_resp = client.post(f"/clientes/{cliente_id}/perfil-financiero", json=perfil_data)
    assert perfil_resp.status_code == 201

    credito_data = {
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 201
    credito_id = credito_resp.json()["credito"]["id"]

    eval_resp = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp.status_code == 200
    
    data = eval_resp.json()
    assert data["decision"] == "RECHAZADO"
    assert "El cliente no tiene capacidad financiera disponible" in data["motivos"]


def test_perfil_financiero_inexistente(client: TestClient):
    """6. Error 404 si el cliente no tiene perfil financiero creado."""
    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    # Creamos crédito pero NO el perfil financiero
    credito_data = {
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 201
    credito_id = credito_resp.json()["credito"]["id"]

    eval_resp = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp.status_code == 404
    assert eval_resp.json()["detail"] == "El cliente no tiene perfil financiero"


def test_credito_inexistente(client: TestClient):
    """7. Error 404 si el crédito a evaluar no existe."""
    eval_resp = client.post("/creditos/999999/evaluar")
    assert eval_resp.status_code == 404
    assert eval_resp.json()["detail"] == "Crédito no encontrado"


def test_actualizacion_manual_estado_patch(client: TestClient):
    """8. Bloqueo de actualización manual a APROBADO o RECHAZADO mediante PATCH."""
    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    credito_data = {
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 201
    credito_id = credito_resp.json()["credito"]["id"]

    # Intentar actualizar estado a RECHAZADO mediante PATCH manual (debe bloquearse con 400)
    patch_resp = client.patch(f"/creditos/{credito_id}/estado", json={"estado": "RECHAZADO"})
    assert patch_resp.status_code == 400
    assert "No se permite establecer los estados APROBADO ni RECHAZADO manualmente" in patch_resp.json()["detail"]

    # Intentar actualizar estado a APROBADO mediante PATCH manual (debe bloquearse con 400)
    patch_resp = client.patch(f"/creditos/{credito_id}/estado", json={"estado": "APROBADO"})
    assert patch_resp.status_code == 400
    assert "No se permite establecer los estados APROBADO ni RECHAZADO manualmente" in patch_resp.json()["detail"]


def test_limites_exactos_monto_y_plazo(client: TestClient):
    """9. Límites exactos: monto $1.500.000 y plazo de 12 meses."""
    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    # Capacidad = 4000000 - 1000000 = 3000000. El 40% es 1.200.000.
    # Monto 1.500.000 a 12 meses al 2.0% tiene una cuota mensual de ~141.838,25 (menor que 1.200.000).
    perfil_data = {
        "ingresos_mensuales": 4000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Desarrollador Senior"
    }
    perfil_resp = client.post(f"/clientes/{cliente_id}/perfil-financiero", json=perfil_data)
    assert perfil_resp.status_code == 201

    # Crédito con límites exactos
    credito_data = {
        "cliente_id": cliente_id,
        "monto": 1500000.0,
        "plazo_meses": 12,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 201
    credito_id = credito_resp.json()["credito"]["id"]

    eval_resp = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp.status_code == 200
    
    data = eval_resp.json()
    assert data["decision"] == "APROBADO"
    assert "El crédito cumple las reglas básicas de evaluación" in data["motivos"]


# ---------------------------------------------------------------------------
# Nuevas pruebas correspondientes a los requerimientos de la Etapa 4
# ---------------------------------------------------------------------------

def test_limite_minimo_valido(client: TestClient):
    """9.1 Límite mínimo válido: monto $500.000 y plazo de 12 meses."""
    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    perfil_data = {
        "ingresos_mensuales": 2000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Auxiliar"
    }
    perfil_resp = client.post(f"/clientes/{cliente_id}/perfil-financiero", json=perfil_data)
    assert perfil_resp.status_code == 201

    # Crédito con límite mínimo exacto ($500.000 COP y 12 meses)
    credito_data = {
        "cliente_id": cliente_id,
        "monto": 500000.0,
        "plazo_meses": 12,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 201
    credito_id = credito_resp.json()["credito"]["id"]

    eval_resp = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp.status_code == 200
    assert eval_resp.json()["decision"] == "APROBADO"


def test_limite_maximo_valido(client: TestClient):
    """9.2 Límite máximo válido: monto $1.500.000 y plazo de 12 meses."""
    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    perfil_data = {
        "ingresos_mensuales": 4000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Ingeniero"
    }
    perfil_resp = client.post(f"/clientes/{cliente_id}/perfil-financiero", json=perfil_data)
    assert perfil_resp.status_code == 201

    # Crédito con límite máximo exacto ($1.500.000 COP y 12 meses)
    credito_data = {
        "cliente_id": cliente_id,
        "monto": 1500000.0,
        "plazo_meses": 12,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 201
    credito_id = credito_resp.json()["credito"]["id"]

    eval_resp = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp.status_code == 200
    assert eval_resp.json()["decision"] == "APROBADO"


def test_bloqueo_segunda_evaluacion(client: TestClient):
    """10. Bloqueo preventivo de re-evaluación sobre un crédito ya finalizado."""
    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    perfil_data = {
        "ingresos_mensuales": 2000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Desarrollador"
    }
    perfil_resp = client.post(f"/clientes/{cliente_id}/perfil-financiero", json=perfil_data)
    assert perfil_resp.status_code == 201

    credito_data = {
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 201
    credito_id = credito_resp.json()["credito"]["id"]

    # Primera evaluación (debe dar 200 OK y quedar APROBADO)
    eval_resp1 = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp1.status_code == 200
    assert eval_resp1.json()["decision"] == "APROBADO"

    # Segunda evaluación (debe dar 400 Bad Request y error exacto)
    eval_resp2 = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp2.status_code == 400
    assert eval_resp2.json()["detail"] == "El crédito ya ha sido evaluado y se encuentra en estado terminal APROBADO."


def test_persistencia_registro_evaluacion_aprobada(client: TestClient):
    """11. Persistencia física del resultado de una evaluación APROBADA en el modelo Evaluacion."""
    from conftest import TestSessionLocal
    from app.models.evaluacion import Evaluacion

    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    perfil_data = {
        "ingresos_mensuales": 2000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 200000.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Desarrollador"
    }
    perfil_resp = client.post(f"/clientes/{cliente_id}/perfil-financiero", json=perfil_data)
    assert perfil_resp.status_code == 201

    credito_data = {
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 201
    credito_id = credito_resp.json()["credito"]["id"]

    # Evaluar crédito
    eval_resp = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp.status_code == 200

    # Consultar base de datos
    db = TestSessionLocal()
    try:
        evaluaciones = db.query(Evaluacion).filter(Evaluacion.credito_id == credito_id).all()
        assert len(evaluaciones) == 1
        
        evaluacion_db = evaluaciones[0]
        assert evaluacion_db.decision == "APROBADO"
        assert float(evaluacion_db.capacidad_mensual) == 800000.0
        assert float(evaluacion_db.cuota_mensual) == 111326.53
        assert evaluacion_db.motivos == "El crédito cumple las reglas básicas de evaluación"
        assert evaluacion_db.fecha_evaluacion is not None
    finally:
        db.close()


def test_persistencia_registro_evaluacion_rechazada(client: TestClient):
    """12. Persistencia física del resultado de una evaluación RECHAZADA en el modelo Evaluacion."""
    from conftest import TestSessionLocal
    from app.models.evaluacion import Evaluacion

    cliente_resp = client.post("/clientes/", json=generar_datos_cliente())
    assert cliente_resp.status_code == 201
    cliente_id = cliente_resp.json()["cliente"]["id"]

    # Capacidad = 300.000 - 100.000 - 50.000 = 150.000. El 40% es 60.000.
    # Cuota calculada para 1.000.000 a 10 meses al 2.0% es de 111.326,53.
    # Supera los 60.000 permitidos, forzando un RECHAZO.
    perfil_data = {
        "ingresos_mensuales": 300000.0,
        "gastos_mensuales": 100000.0,
        "otras_obligaciones": 50000.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Auxiliar"
    }
    perfil_resp = client.post(f"/clientes/{cliente_id}/perfil-financiero", json=perfil_data)
    assert perfil_resp.status_code == 201

    credito_data = {
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    }
    credito_resp = client.post("/creditos/", json=credito_data)
    assert credito_resp.status_code == 201
    credito_id = credito_resp.json()["credito"]["id"]

    # Evaluar crédito (debe ser RECHAZADO)
    eval_resp = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp.status_code == 200
    assert eval_resp.json()["decision"] == "RECHAZADO"

    # Consultar base de datos
    db = TestSessionLocal()
    try:
        evaluaciones = db.query(Evaluacion).filter(Evaluacion.credito_id == credito_id).all()
        assert len(evaluaciones) == 1
        
        evaluacion_db = evaluaciones[0]
        assert evaluacion_db.decision == "RECHAZADO"
        assert float(evaluacion_db.capacidad_mensual) == 150000.0
        assert float(evaluacion_db.cuota_mensual) == 111326.53
        assert "La cuota mensual supera el 40% de la capacidad financiera disponible" in evaluacion_db.motivos
        assert evaluacion_db.fecha_evaluacion is not None
    finally:
        db.close()
