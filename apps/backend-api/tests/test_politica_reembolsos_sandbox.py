from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1.endpoints import politica_reembolsos_sandbox as policy
from app.models.amortizacion import CuotaAmortizacion
from app.models.audit_log import AuditLog
from app.models.pago import Pago
from app.models.solicitud_reembolso import SolicitudReembolsoSandbox
from app.models.usuario import Usuario
from app.models.wompi_pago import WompiPago
from app.models.wompi_reembolso import WompiReembolsoSandbox
from test_wompi_routes import Session, make_event, setup_function


@pytest.fixture(autouse=True)
def preparar(monkeypatch):
    setup_function()
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_test_ficticia")
    monkeypatch.setenv("WOMPI_SANDBOX_REFUND_POLICY_ENABLED", "true")


def crear_pago(monkeypatch):
    event = make_event()
    monkeypatch.setattr(policy, "consultar_transaccion", lambda _id: event["data"]["transaction"])
    db = Session()
    attempt = db.query(WompiPago).one()
    quota = db.query(CuotaAmortizacion).one()
    attempt.estado, attempt.wompi_transaction_id = "PAGADO", "route-tx-001"
    quota.estado, quota.monto_pagado = "PAGADA", Decimal("1250.00")
    db.add(Pago(credito_id=attempt.credito_id, cuota_id=attempt.cuota_id,
                monto_pagado=Decimal("1250.00"), metodo_pago="WOMPI_SANDBOX"))
    admin = Usuario(email="admin-politica@example.invalid", password_hash="x", rol="ADMIN", activo=True)
    db.add(admin)
    db.commit()
    return db, admin


def nueva(**kwargs):
    values = dict(wompi_pago_id=1, monto_centavos=10000, motivo="PAGO_EN_EXCESO",
                  descripcion="Importe excedente de prueba", clasificacion="PASIVO_SALDO_A_FAVOR",
                  evidencia="Caso sintético 123")
    values.update(kwargs)
    return policy.NuevaSolicitud(**values)


def test_aprobacion_separada_no_envia_ni_altera_cartera(monkeypatch):
    db, admin = crear_pago(monkeypatch)
    try:
        quota = db.query(CuotaAmortizacion).one()
        original = (quota.estado, quota.monto_pagado, quota.saldo_remanente, db.query(Pago).count())
        result = policy.crear(nueva(wompi_pago_id=db.query(WompiPago).one().id), db, admin)
        assert result["autorizacion"] == "PENDIENTE" and not result["cartera_modificada"]
        decided = policy.decidir(result["id"], policy.Decision(decision="APROBADA", justificacion="Validación de prueba"), db, admin)
        assert decided["ejecucion"] == "NO_ENVIADO"
        with pytest.raises(HTTPException) as exc:
            policy.ejecutar(result["id"], db, admin)
        assert exc.value.status_code == 409
        db.refresh(quota)
        assert (quota.estado, quota.monto_pagado, quota.saldo_remanente, db.query(Pago).count()) == original
        assert db.query(WompiReembolsoSandbox).count() == 0
        assert db.query(AuditLog).filter_by(entidad="solicitud_reembolso_sandbox").count() == 2
    finally:
        db.close()


def test_apagado_produccion_y_clave_prod_bloqueados(monkeypatch):
    monkeypatch.delenv("WOMPI_SANDBOX_REFUND_POLICY_ENABLED")
    with pytest.raises(HTTPException) as exc:
        policy.exigir_habilitado()
    assert exc.value.status_code == 404
    monkeypatch.setenv("WOMPI_SANDBOX_REFUND_POLICY_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(HTTPException):
        policy.exigir_habilitado()
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_prod_ficticia")
    with pytest.raises(HTTPException):
        policy.exigir_habilitado()


@pytest.mark.parametrize("values", [dict(monto_centavos=0), dict(monto_centavos=True),
    dict(motivo="OTRO", descripcion="Breve causa"), dict(clasificacion=""), dict(evidencia="")])
def test_datos_invalidos(values):
    with pytest.raises(ValidationError):
        nueva(**values)


def test_pago_inexistente_rechazado_y_monto_excesivo(monkeypatch):
    db, admin = crear_pago(monkeypatch)
    try:
        with pytest.raises(HTTPException):
            policy.crear(nueva(wompi_pago_id=999999), db, admin)
        with pytest.raises(HTTPException):
            policy.crear(nueva(wompi_pago_id=db.query(WompiPago).one().id, monto_centavos=125001), db, admin)
        monkeypatch.setattr(policy, "consultar_transaccion", lambda _: {"status": "DECLINED"})
        with pytest.raises(HTTPException):
            policy.crear(nueva(wompi_pago_id=db.query(WompiPago).one().id), db, admin)
        assert db.query(SolicitudReembolsoSandbox).count() == 0
    finally:
        db.close()


def test_historico_y_solicitud_duplicada_bloquean(monkeypatch):
    db, admin = crear_pago(monkeypatch)
    try:
        payment_id = db.query(WompiPago).one().id
        historical = WompiReembolsoSandbox(wompi_pago_id=payment_id, referencia="historic-32935", monto=Decimal("1000"),
                                           escenario="approved", estado="CONFIRMADO", wompi_reembolso_id="32935")
        db.add(historical)
        db.commit()
        with pytest.raises(HTTPException):
            policy.crear(nueva(wompi_pago_id=payment_id), db, admin)
        assert historical.estado == "CONFIRMADO" and historical.wompi_reembolso_id == "32935"
        assert db.query(SolicitudReembolsoSandbox).count() == 0
    finally:
        db.close()


def test_roles_en_backend(client, monkeypatch):
    from app.core.deps import get_current_active_user, get_current_user
    from main import app
    app.dependency_overrides.pop(get_current_active_user, None)
    app.dependency_overrides.pop(get_current_user, None)
    assert client.get("/integraciones/wompi/sandbox/solicitudes-reembolso").status_code in (401, 403)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=1, rol="CLIENTE", activo=True)
    assert client.get("/integraciones/wompi/sandbox/solicitudes-reembolso").status_code == 403
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=1, rol="GESTOR", activo=True)
    assert client.get("/integraciones/wompi/sandbox/solicitudes-reembolso").status_code == 403
