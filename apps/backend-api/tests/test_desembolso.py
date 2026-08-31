import pytest
from fastapi.testclient import TestClient
from decimal import Decimal
from app.models.amortizacion import CuotaAmortizacion
from app.models.evaluacion import Evaluacion
from app.models.credito import Credito
from conftest import TestSessionLocal

# Helper para evitar colisiones de cédula en ejecuciones sucesivas
_ced_counter = 5000000

def generar_datos_cliente_test():
    global _ced_counter
    _ced_counter += 1
    return {
        "nombre": f"Cliente Desembolso {_ced_counter}",
        "cedula": str(_ced_counter),
        "telefono": "3129876543"
    }


@pytest.fixture
def clean_auth_overrides():
    from main import app
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


def test_desembolso_flujo_completo(client: TestClient):
    """
    Paso 2.1: Prueba completa de flujo feliz:
    - Verificación de que /evaluar continúa funcionando correctamente.
    - Desembolso exitoso de un crédito APROBADO por parte de un GESTOR/ADMIN.
    - Cambio de estado correcto a DESEMBOLSADO.
    - Generación correcta de las cuotas de amortización.
    - Verificación de que el monto de cuota coincide con el persistido en Evaluacion (en Decimal).
    - Verificación de que la última cuota deja el saldo_remanente en exactamente Decimal("0.00").
    """
    # 1. Crear cliente
    cli_resp = client.post("/clientes/", json=generar_datos_cliente_test())
    assert cli_resp.status_code == 201
    cliente_id = cli_resp.json()["cliente"]["id"]

    # 2. Crear perfil financiero con excelente capacidad
    perf_resp = client.post(f"/clientes/{cliente_id}/perfil-financiero", json={
        "ingresos_mensuales": 3000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    })
    assert perf_resp.status_code == 201

    # 3. Crear solicitud de crédito válida
    cred_resp = client.post("/creditos/", json={
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    })
    assert cred_resp.status_code == 201
    credito_id = cred_resp.json()["credito"]["id"]

    # 4. Evaluar solicitud (Debe quedar en APROBADO)
    eval_resp = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp.status_code == 200
    eval_data = eval_resp.json()
    assert eval_data["decision"] == "APROBADO"
    cuota_esperada = eval_data["cuota_mensual"]

    # 5. Ejecutar el desembolso (Con el usuario de bypass con rol ADMIN)
    desem_resp = client.post(f"/creditos/{credito_id}/desembolsar")
    assert desem_resp.status_code == 200
    desem_data = desem_resp.json()
    assert desem_data["mensaje"] == "Crédito desembolsado correctamente"
    assert desem_data["credito"]["estado"] == "DESEMBOLSADO"
    assert desem_data["cuotas_generadas"] == 10

    # 6. Consultar la base de datos de pruebas para validar las cuotas generadas
    db = TestSessionLocal()
    try:
        cuotas = (
            db.query(CuotaAmortizacion)
            .filter(CuotaAmortizacion.credito_id == credito_id)
            .order_by(CuotaAmortizacion.numero_cuota)
            .all()
        )
        assert len(cuotas) == 10

        # Verificación monetaria robusta con Decimal: La primera cuota debe coincidir exactamente con Evaluacion
        assert cuotas[0].monto_cuota == Decimal(str(cuota_esperada))
        
        # Verificación monetaria robusta con Decimal: La última cuota debe dejar el saldo remanente en exactamente 0.00
        assert cuotas[-1].saldo_remanente == Decimal("0.00")
        
        # Verificación del comportamiento del amortizador utilizando Decimal
        for i, c in enumerate(cuotas):
            assert c.estado == "PENDIENTE"
            assert c.monto_pagado == Decimal("0.00")
            if i < 9:
                # El saldo remanente es decreciente pero mayor a cero
                assert c.saldo_remanente > Decimal("0.00")
                assert c.saldo_remanente < Decimal("1000000.00")
            else:
                assert c.saldo_remanente == Decimal("0.00")
    finally:
        db.close()



def test_bloqueo_desembolso_estado_invalido(client: TestClient):
    """
    Paso 2.1: Verificar restricciones de la máquina de estados:
    - Crédito SOLICITADO no puede desembolsarse.
    - Crédito RECHAZADO no puede desembolsarse.
    """
    cli_resp = client.post("/clientes/", json=generar_datos_cliente_test())
    cliente_id = cli_resp.json()["cliente"]["id"]
    client.post(f"/clientes/{cliente_id}/perfil-financiero", json={
        "ingresos_mensuales": 3000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    })

    # Crear crédito 1 (Estado inicial: SOLICITADO)
    cred_resp1 = client.post("/creditos/", json={
        "cliente_id": cliente_id,
        "monto": 800000.0,
        "plazo_meses": 6,
        "tasa_interes": 2.0
    })
    credito_solicitado_id = cred_resp1.json()["credito"]["id"]

    # Intentar desembolsar en estado SOLICITADO (Debe fallar con 400)
    desem_resp1 = client.post(f"/creditos/{credito_solicitado_id}/desembolsar")
    assert desem_resp1.status_code == 400
    assert "Debe estar en estado APROBADO" in desem_resp1.json()["detail"]

    # Crear crédito 2 (Forzar RECHAZO por nula capacidad financiera)
    cli_resp2 = client.post("/clientes/", json=generar_datos_cliente_test())
    cliente_id2 = cli_resp2.json()["cliente"]["id"]
    client.post(f"/clientes/{cliente_id2}/perfil-financiero", json={
        "ingresos_mensuales": 100000.0,
        "gastos_mensuales": 99000.0,
        "otras_obligaciones": 50000.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Auxiliar"
    })
    cred_resp2 = client.post("/creditos/", json={
        "cliente_id": cliente_id2,
        "monto": 1500000.0,
        "plazo_meses": 12,
        "tasa_interes": 2.0
    })
    credito_rechazado_id = cred_resp2.json()["credito"]["id"]
    client.post(f"/creditos/{credito_rechazado_id}/evaluar")

    # Intentar desembolsar en estado RECHAZADO (Debe fallar con 400)
    desem_resp2 = client.post(f"/creditos/{credito_rechazado_id}/desembolsar")
    assert desem_resp2.status_code == 400
    assert "Debe estar en estado APROBADO" in desem_resp2.json()["detail"]



def test_bloqueo_desembolso_duplicado_y_evitar_cuotas_duplicadas(client: TestClient):
    """
    Paso 2.1: Verificar re-desembolsos y bloqueo de generación de cuotas duplicadas:
    - Un crédito ya DESEMBOLSADO no puede ser desembolsado nuevamente (secuencial).
    - No se pueden generar cuotas para un crédito que ya tenga amortizaciones.
    """
    cli_resp = client.post("/clientes/", json=generar_datos_cliente_test())
    cliente_id = cli_resp.json()["cliente"]["id"]
    client.post(f"/clientes/{cliente_id}/perfil-financiero", json={
        "ingresos_mensuales": 3000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    })
    cred_resp = client.post("/creditos/", json={
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 12,
        "tasa_interes": 2.0
    })
    credito_id = cred_resp.json()["credito"]["id"]

    # Evaluar
    client.post(f"/creditos/{credito_id}/evaluar")

    # Primer desembolso (Debe ser exitoso)
    resp1 = client.post(f"/creditos/{credito_id}/desembolsar")
    assert resp1.status_code == 200

    # Segundo desembolso secuencial (Debe dar 400 por estar ya DESEMBOLSADO)
    resp2 = client.post(f"/creditos/{credito_id}/desembolsar")
    assert resp2.status_code == 400
    assert "no se puede desembolsar nuevamente" in resp2.json()["detail"]

    # Manipular temporalmente el estado del crédito en base de datos de vuelta a APROBADO
    # pero dejando las cuotas físicas intactas, para verificar el blindaje de CuotaAmortizacion
    db = TestSessionLocal()
    try:
        credito_db = db.query(Credito).filter(Credito.id == credito_id).first()
        credito_db.estado = "APROBADO"
        db.commit()
    finally:
        db.close()

    # Intentar desembolsar de nuevo (Debe rebotar por cuotas preexistentes, evitando duplicados)
    resp3 = client.post(f"/creditos/{credito_id}/desembolsar")
    assert resp3.status_code == 400
    assert "El crédito ya tiene un plan de amortización generado" in resp3.json()["detail"]


def test_cliente_no_puede_desembolsar(client: TestClient):
    """
    Paso 2.1: Verificar control de roles y seguridad:
    - Un usuario con rol CLIENTE no tiene permisos de desembolsar (403).
    - No se asumen IDs quemados (se crea un crédito de manera dinámica y se bloquea con el token del CLIENTE).
    """
    # 1. Crear cliente, perfil, y crédito usando el cliente admin por defecto (para asegurar existencia del ID)
    cli_resp = client.post("/clientes/", json=generar_datos_cliente_test())
    assert cli_resp.status_code == 201
    cliente_id = cli_resp.json()["cliente"]["id"]

    client.post(f"/clientes/{cliente_id}/perfil-financiero", json={
        "ingresos_mensuales": 3000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    })

    cred_resp = client.post("/creditos/", json={
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    })
    assert cred_resp.status_code == 201
    credito_id = cred_resp.json()["credito"]["id"]

    # 2. Registrar un nuevo usuario de tipo CLIENTE para obtener token real
    user_email = "cliente_desem@credifresh.com"
    client.post("/auth/register", json={
        "email": user_email,
        "password": "password123"
    })
    # Login para obtener JWT
    login_resp = client.post("/auth/login", json={
        "email": user_email,
        "password": "password123"
    })
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Desactivar temporalmente los overrides de bypass admin para probar la autorización real
    from main import app
    from app.core.deps import get_current_user, get_current_active_user
    old_current_user = app.dependency_overrides.pop(get_current_user, None)
    old_active_user = app.dependency_overrides.pop(get_current_active_user, None)

    try:
        # Intentar llamar al endpoint de desembolso para el crédito real (Debe dar 403 Forbidden)
        resp = client.post(f"/creditos/{credito_id}/desembolsar", headers=headers)
        assert resp.status_code == 403
    finally:
        # Restaurar los overrides originales para no afectar otras pruebas
        if old_current_user:
            app.dependency_overrides[get_current_user] = old_current_user
        if old_active_user:
            app.dependency_overrides[get_current_active_user] = old_active_user

