import pytest
from fastapi.testclient import TestClient
from decimal import Decimal
from app.models.amortizacion import CuotaAmortizacion
from app.models.pago import Pago as PagoModel
from app.models.credito import Credito
from conftest import TestSessionLocal

# Helper para evitar colisiones de cédula en ejecuciones sucesivas
_ced_counter = 6000000

def generar_datos_cliente_test():
    global _ced_counter
    _ced_counter += 1
    return {
        "nombre": f"Cliente Pagos {_ced_counter}",
        "cedula": str(_ced_counter),
        "telefono": "3129876543"
    }


def preparar_credito_desembolsado(client: TestClient) -> int:
    """Helper para crear un crédito desembolsado y retornar su ID."""
    # 1. Crear cliente
    cli_resp = client.post("/clientes/", json=generar_datos_cliente_test())
    assert cli_resp.status_code == 201
    cliente_id = cli_resp.json()["cliente"]["id"]

    # 2. Crear perfil financiero
    perf_resp = client.post(f"/clientes/{cliente_id}/perfil-financiero", json={
        "ingresos_mensuales": 3000000.0,
        "gastos_mensuales": 1000000.0,
        "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado",
        "actividad_economica": "Analista"
    })
    assert perf_resp.status_code == 201

    # 3. Crear crédito
    cred_resp = client.post("/creditos/", json={
        "cliente_id": cliente_id,
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    })
    assert cred_resp.status_code == 201
    credito_id = cred_resp.json()["credito"]["id"]

    # 4. Evaluar
    eval_resp = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp.status_code == 200

    # 5. Desembolsar
    desem_resp = client.post(f"/creditos/{credito_id}/desembolsar")
    assert desem_resp.status_code == 200

    return credito_id


def test_pago_parcial_exitoso(client: TestClient):
    """1. Registrar un abono menor a la primera cuota (PAGO_PARCIAL) con validación estricta de Decimal."""
    credito_id = preparar_credito_desembolsado(client)

    # El monto de cuota esperada para 1.000.000 COP a 10 meses al 2% es de 111.326,53.
    # Abonamos 50.000.00 (menor a la primera cuota)
    pago_resp = client.post(f"/creditos/{credito_id}/pagos", json={
        "monto": "50000.00",
        "metodo_pago": "TRANSFERENCIA"
    })
    assert pago_resp.status_code == 200
    data = pago_resp.json()
    assert data["mensaje"] == "Pago procesado y aplicado correctamente"
    assert Decimal(str(data["monto_total_recibido"])) == Decimal("50000.00")
    assert data["credito_estado"] == "DESEMBOLSADO"
    assert len(data["distribucion_pagos"]) == 1
    assert data["distribucion_pagos"][0]["numero_cuota"] == 1
    assert Decimal(str(data["distribucion_pagos"][0]["monto_aplicado"])) == Decimal("50000.00")
    assert data["distribucion_pagos"][0]["cuota_estado_resultante"] == "PAGO_PARCIAL"

    # Consultar base de datos para aserciones de consistencia física con Decimal
    db = TestSessionLocal()
    try:
        cuotas = db.query(CuotaAmortizacion).filter(CuotaAmortizacion.credito_id == credito_id).order_by(CuotaAmortizacion.numero_cuota).all()
        assert cuotas[0].estado == "PAGO_PARCIAL"
        assert cuotas[0].monto_pagado == Decimal("50000.00")
        
        pagos_db = db.query(PagoModel).filter(PagoModel.credito_id == credito_id).all()
        assert len(pagos_db) == 1
        assert pagos_db[0].monto_pagado == Decimal("50000.00")
        assert pagos_db[0].cuota_id == cuotas[0].id
    finally:
        db.close()



def test_pago_parcial_acumulativo(client: TestClient):
    """2. Realizar múltiples pagos parciales acumulativos sobre la misma cuota."""
    credito_id = preparar_credito_desembolsado(client)

    # 1er Abono: 50.000
    client.post(f"/creditos/{credito_id}/pagos", json={"monto": "50000.00", "metodo_pago": "TRANSFERENCIA"})
    # 2do Abono: 30.000
    pago_resp2 = client.post(f"/creditos/{credito_id}/pagos", json={"monto": "30000.00", "metodo_pago": "PSE"})
    assert pago_resp2.status_code == 200
    
    db = TestSessionLocal()
    try:
        cuotas = db.query(CuotaAmortizacion).filter(CuotaAmortizacion.credito_id == credito_id).order_by(CuotaAmortizacion.numero_cuota).all()
        assert cuotas[0].estado == "PAGO_PARCIAL"
        assert cuotas[0].monto_pagado == Decimal("80000.00")
        
        # 3er Abono para liquidar la cuota 1 (restan exactamente 31.326,53)
        pago_resp3 = client.post(f"/creditos/{credito_id}/pagos", json={"monto": "31326.53", "metodo_pago": "EFECTIVO"})
        assert pago_resp3.status_code == 200
        
        db.refresh(cuotas[0])
        assert cuotas[0].estado == "PAGADA"
        assert cuotas[0].monto_pagado == Decimal("111326.53")
        
        pagos_db = db.query(PagoModel).filter(PagoModel.cuota_id == cuotas[0].id).all()
        assert len(pagos_db) == 3
        assert sum(p.monto_pagado for p in pagos_db) == Decimal("111326.53")
    finally:
        db.close()


def test_pago_multicompensacion_sobrepago(client: TestClient):
    """3. Registrar abono que compensa la primera cuota y genera abono parcial a la segunda."""
    credito_id = preparar_credito_desembolsado(client)

    # Cuota 1 esperada: 111.326,53. Abonamos 150.000,00
    # Sobran exactamente 38.673,47 para la cuota 2.
    pago_resp = client.post(f"/creditos/{credito_id}/pagos", json={
        "monto": "150000.00",
        "metodo_pago": "TRANSFERENCIA"
    })
    assert pago_resp.status_code == 200
    data = pago_resp.json()
    assert len(data["distribucion_pagos"]) == 2
    assert data["distribucion_pagos"][0]["numero_cuota"] == 1
    assert Decimal(str(data["distribucion_pagos"][0]["monto_aplicado"])) == Decimal("111326.53")
    assert data["distribucion_pagos"][0]["cuota_estado_resultante"] == "PAGADA"

    assert data["distribucion_pagos"][1]["numero_cuota"] == 2
    assert Decimal(str(data["distribucion_pagos"][1]["monto_aplicado"])) == Decimal("38673.47")
    assert data["distribucion_pagos"][1]["cuota_estado_resultante"] == "PAGO_PARCIAL"

    db = TestSessionLocal()
    try:
        cuotas = db.query(CuotaAmortizacion).filter(CuotaAmortizacion.credito_id == credito_id).order_by(CuotaAmortizacion.numero_cuota).all()
        assert cuotas[0].estado == "PAGADA"
        assert cuotas[0].monto_pagado == Decimal("111326.53")
        assert cuotas[1].estado == "PAGO_PARCIAL"
        assert cuotas[1].monto_pagado == Decimal("38673.47")

        pagos_db = db.query(PagoModel).filter(PagoModel.credito_id == credito_id).order_by(PagoModel.id).all()
        assert len(pagos_db) == 2
        assert pagos_db[0].cuota_id == cuotas[0].id
        assert pagos_db[0].monto_pagado == Decimal("111326.53")
        assert pagos_db[1].cuota_id == cuotas[1].id
        assert pagos_db[1].monto_pagado == Decimal("38673.47")
    finally:
        db.close()


def test_pago_exactamente_igual_deuda_total(client: TestClient):
    """4. Pagar el valor exacto de toda la deuda pendiente, cerrando el crédito a PAGADO sin casteos float."""
    credito_id = preparar_credito_desembolsado(client)

    db = TestSessionLocal()
    try:
        cuotas = db.query(CuotaAmortizacion).filter(CuotaAmortizacion.credito_id == credito_id).all()
        deuda_total = sum(c.monto_cuota for c in cuotas)
    finally:
        db.close()

    # Pagar la deuda total exacta pasando el string exacto de la deuda
    pago_resp = client.post(f"/creditos/{credito_id}/pagos", json={
        "monto": str(deuda_total),
        "metodo_pago": "TRANSFERENCIA"
    })
    assert pago_resp.status_code == 200
    data = pago_resp.json()
    assert data["credito_estado"] == "PAGADO"
    assert Decimal(str(data["monto_total_recibido"])) == deuda_total

    db = TestSessionLocal()
    try:
        credito_db = db.query(Credito).filter(Credito.id == credito_id).first()
        assert credito_db.estado == "PAGADO"
        
        cuotas_db = db.query(CuotaAmortizacion).filter(CuotaAmortizacion.credito_id == credito_id).all()
        assert all(c.estado == "PAGADA" for c in cuotas_db)
        assert all(c.monto_pagado == c.monto_cuota for c in cuotas_db)
    finally:
        db.close()



def test_bloqueo_pago_excedente_deuda_total(client: TestClient):
    """5. Impedir pagos que superen la deuda total vigente."""
    credito_id = preparar_credito_desembolsado(client)

    db = TestSessionLocal()
    try:
        cuotas = db.query(CuotaAmortizacion).filter(CuotaAmortizacion.credito_id == credito_id).all()
        deuda_total = sum(c.monto_cuota for c in cuotas)
    finally:
        db.close()

    # Intentar pagar deuda_total + 100 COP (debe rebotar con 400)
    monto_excedente = deuda_total + Decimal("100.00")
    pago_resp = client.post(f"/creditos/{credito_id}/pagos", json={
        "monto": str(monto_excedente),
        "metodo_pago": "TRANSFERENCIA"
    })
    assert pago_resp.status_code == 400
    assert "excede la deuda pendiente total" in pago_resp.json()["detail"]


def test_bloqueo_pagos_estados_invalidos(client: TestClient):
    """6. Impedir registrar pagos sobre créditos que no estén en estado DESEMBOLSADO (SOLICITADO, APROBADO y RECHAZADO)."""
    # 1. Caso SOLICITADO
    cli_resp = client.post("/clientes/", json=generar_datos_cliente_test())
    cliente_id = cli_resp.json()["cliente"]["id"]
    client.post(f"/clientes/{cliente_id}/perfil-financiero", json={
        "ingresos_mensuales": 3000000.0, "gastos_mensuales": 1000000.0, "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado", "actividad_economica": "Analista"
    })
    cred_resp = client.post("/creditos/", json={
        "cliente_id": cliente_id, "monto": 1000000.0, "plazo_meses": 10, "tasa_interes": 2.0
    })
    credito_solicitado_id = cred_resp.json()["credito"]["id"]

    # Intentar pagar sobre crédito SOLICITADO (debe fallar con 400)
    pago_resp1 = client.post(f"/creditos/{credito_solicitado_id}/pagos", json={
        "monto": "10000.00", "metodo_pago": "TRANSFERENCIA"
    })
    assert pago_resp1.status_code == 400
    assert "Debe estar DESEMBOLSADO" in pago_resp1.json()["detail"]

    # 2. Caso APROBADO (Evaluado pero no desembolsado)
    client.post(f"/creditos/{credito_solicitado_id}/evaluar")
    pago_resp2 = client.post(f"/creditos/{credito_solicitado_id}/pagos", json={
        "monto": "10000.00", "metodo_pago": "TRANSFERENCIA"
    })
    assert pago_resp2.status_code == 400
    assert "Debe estar DESEMBOLSADO" in pago_resp2.json()["detail"]

    # 3. Caso RECHAZADO (Evaluado con rechazo)
    cli_resp2 = client.post("/clientes/", json=generar_datos_cliente_test())
    cliente_id2 = cli_resp2.json()["cliente"]["id"]
    client.post(f"/clientes/{cliente_id2}/perfil-financiero", json={
        "ingresos_mensuales": 100000.0, "gastos_mensuales": 99000.0, "otras_obligaciones": 50000.0,
        "tipo_ingresos": "Empleado", "actividad_economica": "Auxiliar"
    })
    cred_resp2 = client.post("/creditos/", json={
        "cliente_id": cliente_id2, "monto": 1500000.0, "plazo_meses": 12, "tasa_interes": 2.0
    })
    credito_rechazado_id = cred_resp2.json()["credito"]["id"]
    eval_resp = client.post(f"/creditos/{credito_rechazado_id}/evaluar")
    assert eval_resp.status_code == 200
    assert eval_resp.json()["decision"] == "RECHAZADO"

    # Intentar pagar sobre crédito RECHAZADO (debe fallar con 400)
    pago_resp3 = client.post(f"/creditos/{credito_rechazado_id}/pagos", json={
        "monto": "10000.00", "metodo_pago": "TRANSFERENCIA"
    })
    assert pago_resp3.status_code == 400
    assert "Debe estar DESEMBOLSADO" in pago_resp3.json()["detail"]


def test_bloqueo_pago_credito_ya_pagado(client: TestClient):
    """7. Impedir registrar pagos sobre un crédito que ya fue saldado al 100%."""
    credito_id = preparar_credito_desembolsado(client)

    db = TestSessionLocal()
    try:
        cuotas = db.query(CuotaAmortizacion).filter(CuotaAmortizacion.credito_id == credito_id).all()
        deuda_total = sum(c.monto_cuota for c in cuotas)
    finally:
        db.close()

    # Liquidar crédito
    client.post(f"/creditos/{credito_id}/pagos", json={"monto": str(deuda_total), "metodo_pago": "TRANSFERENCIA"})

    # Intentar abonar de nuevo (debe fallar con 400)
    pago_resp = client.post(f"/creditos/{credito_id}/pagos", json={"monto": "10000.00", "metodo_pago": "TRANSFERENCIA"})
    assert pago_resp.status_code == 400
    assert "Debe estar DESEMBOLSADO" in pago_resp.json()["detail"]



def test_control_roles_cliente_no_puede_pagar(client: TestClient):
    """8. Un usuario con rol CLIENTE recibe 403 al intentar registrar un pago."""
    credito_id = preparar_credito_desembolsado(client)

    # Registrar cliente y obtener token
    user_email = "cliente_pagador@credifresh.com"
    client.post("/auth/register", json={"email": user_email, "password": "password123"})
    login_resp = client.post("/auth/login", json={"email": user_email, "password": "password123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Desactivar temporalmente overrides de admin para probar rol CLIENTE real
    from main import app
    from app.core.deps import get_current_user, get_current_active_user
    old_current_user = app.dependency_overrides.pop(get_current_user, None)
    old_active_user = app.dependency_overrides.pop(get_current_active_user, None)

    try:
        pago_resp = client.post(f"/creditos/{credito_id}/pagos", json={
            "monto": "50000.00",
            "metodo_pago": "TRANSFERENCIA"
        }, headers=headers)
        assert pago_resp.status_code == 403
    finally:
        if old_current_user:
            app.dependency_overrides[get_current_user] = old_current_user
        if old_active_user:
            app.dependency_overrides[get_current_active_user] = old_active_user


def test_consulta_amortizacion_exitoso_gestor_admin(client: TestClient):
    """9. Un GESTOR o ADMIN puede consultar la amortización de cualquier crédito (con validaciones de Decimal)."""
    credito_id = preparar_credito_desembolsado(client)

    resp = client.get(f"/creditos/{credito_id}/amortizacion")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 10
    assert data[0]["numero_cuota"] == 1
    
    # Validaciones Decimal estrictas
    assert Decimal(str(data[0]["monto_cuota"])) > Decimal("0.00")
    assert Decimal(str(data[0]["saldo_remanente"])) > Decimal("0.00")
    assert Decimal(str(data[-1]["saldo_remanente"])) == Decimal("0.00")


def test_consulta_amortizacion_propio_cliente(client: TestClient):
    """10. Un CLIENTE puede consultar la amortización de su propio crédito."""
    # Registrar el usuario mediante el endpoint oficial
    user_email = "dueno@credifresh.com"
    reg_resp = client.post("/auth/register", json={"email": user_email, "password": "password123"})
    assert reg_resp.status_code == 201
    user_id = reg_resp.json()["id"]

    db = TestSessionLocal()
    from app.models.cliente import Cliente as ClienteModel
    try:
        cli = ClienteModel(nombre="Dueño Crédito", cedula="8888123", telefono="3120000000", usuario_id=user_id)
        db.add(cli)
        db.commit()
        db.refresh(cli)
        cliente_id = cli.id
    finally:
        db.close()

    # Crear perfil, crédito y desembolsar como ADMIN (bypass temporal)
    client.post(f"/clientes/{cliente_id}/perfil-financiero", json={
        "ingresos_mensuales": 3000000.0, "gastos_mensuales": 1000000.0, "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado", "actividad_economica": "Analista"
    })
    cred_resp = client.post("/creditos/", json={
        "cliente_id": cliente_id, "monto": 1000000.0, "plazo_meses": 10, "tasa_interes": 2.0
    })
    credito_id = cred_resp.json()["credito"]["id"]
    client.post(f"/creditos/{credito_id}/evaluar")
    client.post(f"/creditos/{credito_id}/desembolsar")

    # Iniciar sesión con el usuario recién registrado
    login_resp = client.post("/auth/login", json={"email": user_email, "password": "password123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Desactivar temporalmente los overrides admin
    from main import app
    from app.core.deps import get_current_user, get_current_active_user
    old_current_user = app.dependency_overrides.pop(get_current_user, None)
    old_active_user = app.dependency_overrides.pop(get_current_active_user, None)

    try:
        resp = client.get(f"/creditos/{credito_id}/amortizacion", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 10
        assert Decimal(str(data[0]["monto_cuota"])) > Decimal("0.00")
        assert Decimal(str(data[-1]["saldo_remanente"])) == Decimal("0.00")
    finally:
        if old_current_user:
            app.dependency_overrides[get_current_user] = old_current_user
        if old_active_user:
            app.dependency_overrides[get_current_active_user] = old_active_user



def test_consulta_pagos_exitoso_gestor_admin(client: TestClient):
    """11. Un GESTOR o ADMIN puede consultar el historial de pagos de cualquier crédito (con validaciones de Decimal)."""
    credito_id = preparar_credito_desembolsado(client)

    # Realizar un pago
    client.post(f"/creditos/{credito_id}/pagos", json={"monto": "150000.00", "metodo_pago": "TRANSFERENCIA"})

    # Consultar historial
    resp = client.get(f"/creditos/{credito_id}/pagos")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2  # Dos abonos físicos persistidos por el fraccionamiento
    montos_recibidos = {Decimal(str(data[0]["monto_pagado"])), Decimal(str(data[1]["monto_pagado"]))}
    assert montos_recibidos == {Decimal("111326.53"), Decimal("38673.47")}


def test_consulta_pagos_propio_cliente(client: TestClient):
    """12. Un CLIENTE puede consultar su propio historial de pagos (con validaciones de Decimal)."""
    # Registrar el usuario mediante el endpoint oficial
    user_email = "duenopago@credifresh.com"
    reg_resp = client.post("/auth/register", json={"email": user_email, "password": "password123"})
    assert reg_resp.status_code == 201
    user_id = reg_resp.json()["id"]

    db = TestSessionLocal()
    from app.models.cliente import Cliente as ClienteModel
    try:
        cli = ClienteModel(nombre="Dueño Pagos", cedula="8888456", telefono="3120000000", usuario_id=user_id)
        db.add(cli)
        db.commit()
        db.refresh(cli)
        cliente_id = cli.id
    finally:
        db.close()

    # Crear perfil, crédito, desembolsar y abonar como ADMIN
    client.post(f"/clientes/{cliente_id}/perfil-financiero", json={
        "ingresos_mensuales": 3000000.0, "gastos_mensuales": 1000000.0, "otras_obligaciones": 0.0,
        "tipo_ingresos": "Empleado", "actividad_economica": "Analista"
    })
    cred_resp = client.post("/creditos/", json={
        "cliente_id": cliente_id, "monto": 1000000.0, "plazo_meses": 10, "tasa_interes": 2.0
    })
    credito_id = cred_resp.json()["credito"]["id"]
    client.post(f"/creditos/{credito_id}/evaluar")
    client.post(f"/creditos/{credito_id}/desembolsar")
    client.post(f"/creditos/{credito_id}/pagos", json={"monto": "50000.00", "metodo_pago": "TRANSFERENCIA"})

    # Iniciar sesión con el usuario recién registrado
    login_resp = client.post("/auth/login", json={"email": user_email, "password": "password123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Desactivar temporalmente los overrides admin
    from main import app
    from app.core.deps import get_current_user, get_current_active_user
    old_current_user = app.dependency_overrides.pop(get_current_user, None)
    old_active_user = app.dependency_overrides.pop(get_current_active_user, None)

    try:
        resp = client.get(f"/creditos/{credito_id}/pagos", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert Decimal(str(data[0]["monto_pagado"])) == Decimal("50000.00")
        assert data[0]["metodo_pago"] == "TRANSFERENCIA"
    finally:
        if old_current_user:
            app.dependency_overrides[get_current_user] = old_current_user
        if old_active_user:
            app.dependency_overrides[get_current_active_user] = old_active_user


def test_consulta_amortizacion_idor_cliente_bloqueado(client: TestClient):
    """13. Un CLIENTE recibe 403 al intentar consultar la amortización de un tercero (IDOR)."""
    credito_id_ajeno = preparar_credito_desembolsado(client)

    # Iniciar sesión como CLIENTE tercero
    user_email = "tercero@credifresh.com"
    client.post("/auth/register", json={"email": user_email, "password": "password123"})
    login_resp = client.post("/auth/login", json={"email": user_email, "password": "password123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Desactivar temporalmente los overrides admin
    from main import app
    from app.core.deps import get_current_user, get_current_active_user
    old_current_user = app.dependency_overrides.pop(get_current_user, None)
    old_active_user = app.dependency_overrides.pop(get_current_active_user, None)

    try:
        resp = client.get(f"/creditos/{credito_id_ajeno}/amortizacion", headers=headers)
        assert resp.status_code == 403
    finally:
        if old_current_user:
            app.dependency_overrides[get_current_user] = old_current_user
        if old_active_user:
            app.dependency_overrides[get_current_active_user] = old_active_user


def test_consulta_pagos_idor_cliente_bloqueado(client: TestClient):
    """14. Un CLIENTE recibe 403 al intentar consultar el historial de pagos de un tercero (IDOR)."""
    credito_id_ajeno = preparar_credito_desembolsado(client)

    # Iniciar sesión como CLIENTE tercero
    user_email = "tercero2@credifresh.com"
    client.post("/auth/register", json={"email": user_email, "password": "password123"})
    login_resp = client.post("/auth/login", json={"email": user_email, "password": "password123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Desactivar temporalmente los overrides admin
    from main import app
    from app.core.deps import get_current_user, get_current_active_user
    old_current_user = app.dependency_overrides.pop(get_current_user, None)
    old_active_user = app.dependency_overrides.pop(get_current_active_user, None)

    try:
        resp = client.get(f"/creditos/{credito_id_ajeno}/pagos", headers=headers)
        assert resp.status_code == 403
    finally:
        if old_current_user:
            app.dependency_overrides[get_current_user] = old_current_user
        if old_active_user:
            app.dependency_overrides[get_current_active_user] = old_active_user