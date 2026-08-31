import pytest
from fastapi.testclient import TestClient
from decimal import Decimal
from conftest import TestSessionLocal
from app.models.audit_log import AuditLog
from app.models.credito import Credito
from app.models.amortizacion import CuotaAmortizacion

_ced_auditoria = 9000000

def generar_datos_cliente_auditoria():
    global _ced_auditoria
    _ced_auditoria += 1
    return {
        "nombre": f"Cliente Auditoria {_ced_auditoria}",
        "cedula": str(_ced_auditoria),
        "telefono": "3100000000"
    }


def preparar_credito_para_auditoria(client: TestClient) -> int:
    cli_resp = client.post("/clientes/", json=generar_datos_cliente_auditoria())
    assert cli_resp.status_code == 201
    cliente_id = cli_resp.json()["cliente"]["id"]

    client.post(f"/clientes/{cliente_id}/perfil-financiero", json={
        "ingresos_mensuales": 4000000.0,
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
    return cred_resp.json()["credito"]["id"]


def test_auditoria_evaluacion_automatica(client: TestClient):
    """1. Verificar que una evaluación exitosa genere EVALUAR_CREDITO."""
    credito_id = preparar_credito_para_auditoria(client)

    eval_resp = client.post(f"/creditos/{credito_id}/evaluar")
    assert eval_resp.status_code == 200

    db = TestSessionLocal()
    try:
        log = db.query(AuditLog).filter(
            AuditLog.accion == "EVALUAR_CREDITO",
            AuditLog.entidad_id == credito_id
        ).first()
        assert log is not None
        assert log.resultado == "EXITOSO"
        assert log.entidad == "credito"
    finally:
        db.close()


def test_auditoria_cambio_estado_automatico(client: TestClient):
    """2. Verificar que un cambio de estado exitoso genere CAMBIAR_ESTADO_CREDITO."""
    credito_id = preparar_credito_para_auditoria(client)
    
    patch_resp = client.patch(f"/creditos/{credito_id}/estado", json={"estado": "RECHAZADO"})
    assert patch_resp.status_code == 400
    assert "No se permite establecer los estados APROBADO ni RECHAZADO manualmente" in patch_resp.json()["detail"]



def test_auditoria_desembolso_automatico(client: TestClient):
    """3. Verificar que un desembolso genere DESEMBOLSAR_CREDITO."""
    credito_id = preparar_credito_para_auditoria(client)
    client.post(f"/creditos/{credito_id}/evaluar")
    client.patch(f"/creditos/{credito_id}/estado", json={"estado": "APROBADO"})

    desem_resp = client.post(f"/creditos/{credito_id}/desembolsar")
    assert desem_resp.status_code == 200

    db = TestSessionLocal()
    try:
        log = db.query(AuditLog).filter(
            AuditLog.accion == "DESEMBOLSAR_CREDITO",
            AuditLog.entidad_id == credito_id
        ).first()
        assert log is not None
        assert log.resultado == "EXITOSO"
    finally:
        db.close()


def test_auditoria_pago_y_liquidacion(client: TestClient):
    """4. Verificar pago y liquidación (REGISTRAR_PAGO y LIQUIDAR_CREDITO)."""
    credito_id = preparar_credito_para_auditoria(client)
    client.post(f"/creditos/{credito_id}/evaluar")
    client.post(f"/creditos/{credito_id}/desembolsar")

    db = TestSessionLocal()
    try:
        cuotas = db.query(CuotaAmortizacion).filter(CuotaAmortizacion.credito_id == credito_id).all()
        deuda_total = sum(c.monto_cuota for c in cuotas)
    finally:
        db.close()

    pago_resp = client.post(f"/creditos/{credito_id}/pagos", json={
        "monto": str(deuda_total),
        "metodo_pago": "TRANSFERENCIA"
    })
    assert pago_resp.status_code == 200

    db = TestSessionLocal()
    try:
        log_pago = db.query(AuditLog).filter(
            AuditLog.accion == "REGISTRAR_PAGO",
            AuditLog.entidad_id == credito_id
        ).first()
        assert log_pago is not None

        log_liq = db.query(AuditLog).filter(
            AuditLog.accion == "LIQUIDAR_CREDITO",
            AuditLog.entidad_id == credito_id
        ).first()
        assert log_liq is not None
        assert "PAGADO" in log_liq.detalles
    finally:
        db.close()


def test_consulta_auditoria_exitoso_admin(client: TestClient):
    """5. Verificar que ADMIN pueda consultar /auditoria."""
    resp = client.get("/auditoria")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_consulta_auditoria_bloqueado_gestor_cliente_sin_auth(client: TestClient):
    """6. Verificar GESTOR (403), CLIENTE (403) y sin token (401)."""
    client.post("/auth/register", json={"email": "gestoraud@credifresh.com", "password": "password123", "rol": "GESTOR"})
    login_gestor = client.post("/auth/login", json={"email": "gestoraud@credifresh.com", "password": "password123"})
    token_gestor = login_gestor.json()["access_token"]
    headers_gestor = {"Authorization": f"Bearer {token_gestor}"}

    client.post("/auth/register", json={"email": "clienteaud@credifresh.com", "password": "password123", "rol": "CLIENTE"})
    login_cliente = client.post("/auth/login", json={"email": "clienteaud@credifresh.com", "password": "password123"})
    token_cliente = login_cliente.json()["access_token"]
    headers_cliente = {"Authorization": f"Bearer {token_cliente}"}

    from main import app
    from app.core.deps import get_current_user, get_current_active_user
    old_user = app.dependency_overrides.pop(get_current_user, None)
    old_active = app.dependency_overrides.pop(get_current_active_user, None)

    try:
        resp_g = client.get("/auditoria", headers=headers_gestor)
        assert resp_g.status_code == 403

        resp_c = client.get("/auditoria", headers=headers_cliente)
        assert resp_c.status_code == 403

        resp_no_auth = client.get("/auditoria")
        assert resp_no_auth.status_code == 401
    finally:
        if old_user:
            app.dependency_overrides[get_current_user] = old_user
        if old_active:
            app.dependency_overrides[get_current_active_user] = old_active


def test_auditoria_append_only_y_datos_sensibles(client: TestClient):
    """7. Verificar append-only y ausencia de datos sensibles en logs."""
    resp_put = client.put("/auditoria/1", json={})
    assert resp_put.status_code == 404

    resp_delete = client.delete("/auditoria/1")
    assert resp_delete.status_code == 404

    db = TestSessionLocal()
    try:
        logs = db.query(AuditLog).all()
        for log in logs:
            if log.detalles:
                detalles_lower = log.detalles.lower()
                assert "password" not in detalles_lower
                assert "secret" not in detalles_lower
                assert "token" not in detalles_lower
                assert "key" not in detalles_lower
    finally:
        db.close()
