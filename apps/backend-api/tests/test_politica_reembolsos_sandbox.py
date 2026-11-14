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
    enviados = []
    monkeypatch.setattr(policy, "solicitar_reembolso_sandbox", lambda **kw: (enviados.append(kw) or {"status": "APPROVED", "refund_id": "ficticio"}))
    try:
        quota = db.query(CuotaAmortizacion).one()
        original = (quota.estado, quota.monto_pagado, quota.saldo_remanente, db.query(Pago).count())
        result = policy.crear(nueva(wompi_pago_id=db.query(WompiPago).one().id), db, admin)
        assert result["autorizacion"] == "PENDIENTE" and not result["cartera_modificada"]
        decided = policy.decidir(result["id"], policy.Decision(decision="APROBADA", justificacion="Validación de prueba"), db, admin)
        assert decided["ejecucion"] == "NO_ENVIADO"
        assert not enviados
        assert policy.ejecutar(result["id"], db, admin)["ejecucion"] == "CONFIRMADO"
        with pytest.raises(HTTPException) as exc:
            policy.ejecutar(result["id"], db, admin)
        assert exc.value.status_code == 409
        db.refresh(quota)
        assert (quota.estado, quota.monto_pagado, quota.saldo_remanente, db.query(Pago).count()) == original
        assert db.query(WompiReembolsoSandbox).count() == 1 and len(enviados) == 1
        assert db.query(AuditLog).filter_by(entidad="solicitud_reembolso_sandbox").count() == 4
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


def test_ruta_anterior_bloqueada_sin_llamada_a_wompi(monkeypatch):
    from app.api.v1.endpoints import wompi
    monkeypatch.setattr(wompi, "solicitar_reembolso_sandbox", lambda **_: pytest.fail("No debe enviarse"))
    db, admin = crear_pago(monkeypatch)
    try:
        with pytest.raises(HTTPException) as exc:
            wompi.crear_reembolso_de_prueba(1, 1, wompi.ReembolsoSandboxInput(monto_centavos=100, escenario="approved"), db, admin)
        assert exc.value.status_code == 409
    finally:
        db.close()


def test_timeout_reservado_sin_reenvio(monkeypatch):
    db, admin = crear_pago(monkeypatch)
    calls = []
    def timeout(**kwargs):
        calls.append(kwargs)
        raise TimeoutError()
    monkeypatch.setattr(policy, "solicitar_reembolso_sandbox", timeout)
    try:
        request = policy.crear(nueva(wompi_pago_id=db.query(WompiPago).one().id), db, admin)
        policy.decidir(request["id"], policy.Decision(decision="APROBADA", justificacion="Revisión de prueba"), db, admin)
        assert policy.ejecutar(request["id"], db, admin)["ejecucion"] == "INCIERTO"
        with pytest.raises(HTTPException):
            policy.ejecutar(request["id"], db, admin)
        assert len(calls) == 1
        assert db.query(CuotaAmortizacion).one().monto_pagado == Decimal("1250.00")
    finally:
        db.close()


def test_ambas_rutas_exigen_aprobacion_y_flag(monkeypatch):
    from app.api.v1.endpoints import wompi
    db, admin = crear_pago(monkeypatch)
    llamadas = []
    monkeypatch.setattr(policy, "solicitar_reembolso_sandbox", lambda **kw: llamadas.append(kw))
    try:
        row = policy.crear(nueva(wompi_pago_id=db.query(WompiPago).one().id), db, admin)
        legacy = wompi.ReembolsoSandboxInput(monto_centavos=10000, escenario="approved")
        for fn in (lambda: policy.ejecutar(row["id"], db, admin),
                   lambda: wompi.crear_reembolso_de_prueba(row["credito_id"], row["cuota_id"], legacy, db, admin)):
            with pytest.raises(HTTPException):
                fn()
        policy.decidir(row["id"], policy.Decision(decision="APROBADA", justificacion="Aprobación sintética"), db, admin)
        monkeypatch.delenv("WOMPI_SANDBOX_REFUND_POLICY_ENABLED")
        for fn in (lambda: policy.ejecutar(row["id"], db, admin),
                   lambda: wompi.crear_reembolso_de_prueba(row["credito_id"], row["cuota_id"], legacy, db, admin)):
            with pytest.raises(HTTPException):
                fn()
        assert not llamadas and db.query(WompiReembolsoSandbox).count() == 0
        assert db.query(CuotaAmortizacion).one().monto_pagado == Decimal("1250.00")
    finally:
        db.close()


def test_verificacion_y_conciliacion_idempotentes(monkeypatch):
    db, admin = crear_pago(monkeypatch)
    monkeypatch.setattr(policy, "solicitar_reembolso_sandbox", lambda **_: {"status": "APPROVED", "refund_id": "12345"})
    monkeypatch.setattr(policy, "consultar_reembolso_sandbox", lambda _: {"respuesta_http_wompi": 200,
        "datos_confirmados": True, "transaction_id": "route-tx-001", "monto_centavos": 10000, "estado": "APPROVED"})
    try:
        request = policy.crear(nueva(wompi_pago_id=db.query(WompiPago).one().id), db, admin)
        sid = request["id"]
        policy.decidir(sid, policy.Decision(decision="APROBADA", justificacion="Aprobación de prueba"), db, admin)
        policy.ejecutar(sid, db, admin)
        assert not policy.verificar(sid, policy.ConsultaProveedor(refund_id="12345"), db, admin)["ya_verificado"]
        assert policy.verificar(sid, policy.ConsultaProveedor(refund_id="12345"), db, admin)["ya_verificado"]
        data = policy.RevisionContable(resultado="APROBADA", observacion="Cotejo ficticio verificado")
        assert not policy.conciliar_operativamente(sid, data, db, admin)["ya_cotejado"]
        assert policy.conciliar_operativamente(sid, data, db, admin)["ya_cotejado"]
        assert db.query(CuotaAmortizacion).one().monto_pagado == Decimal("1250.00")
    finally:
        db.close()


def test_diagnostico_reservas_no_modifica_ni_reenvia(monkeypatch):
    from datetime import datetime, timedelta, timezone
    db, admin = crear_pago(monkeypatch)
    try:
        monkeypatch.setenv("WOMPI_REFUND_STALE_MINUTES", "0")
        with pytest.raises(HTTPException):
            policy.reservas_posiblemente_abandonadas(db, admin)
        monkeypatch.setenv("WOMPI_REFUND_STALE_MINUTES", "30")
        result = policy.reservas_posiblemente_abandonadas(db, admin)
        assert result["operaciones"] == []
        monkeypatch.setattr(policy, "solicitar_reembolso_sandbox", lambda **_: {"status": "APPROVED", "refund_id": "12345"})
        solicitud = policy.crear(nueva(wompi_pago_id=db.query(WompiPago).one().id), db, admin)
        policy.decidir(solicitud["id"], policy.Decision(decision="APROBADA", justificacion="Validación sintética"), db, admin)
        policy.ejecutar(solicitud["id"], db, admin)
        s = db.get(SolicitudReembolsoSandbox, solicitud["id"])
        refund = db.get(WompiReembolsoSandbox, s.reembolso_id)
        s.ejecucion, refund.estado = "CREANDO", "CREANDO"
        refund.creado_en = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        diagnostic = policy.reservas_posiblemente_abandonadas(db, admin)
        assert len(diagnostic["operaciones"]) == 1
        assert diagnostic["operaciones"][0]["actividad_confirmada"] is None
        assert s.ejecucion == "CREANDO" and refund.estado == "CREANDO"
        assert db.query(Pago).count() == 1
        assert db.query(CuotaAmortizacion).one().monto_pagado == Decimal("1250.00")
    finally:
        db.close()


@pytest.mark.parametrize("changed", [{"estado": "DECLINED"}, {"monto_centavos": 10001}, {"transaction_id": "otra"}])
def test_respuesta_contradictoria_deja_alerta_y_no_modifica_cartera(monkeypatch, changed):
    db, admin = crear_pago(monkeypatch)
    monkeypatch.setattr(policy, "solicitar_reembolso_sandbox", lambda **_: {"status": "APPROVED", "refund_id": "12345"})
    try:
        request = policy.crear(nueva(wompi_pago_id=db.query(WompiPago).one().id), db, admin)
        sid = request["id"]
        policy.decidir(sid, policy.Decision(decision="APROBADA", justificacion="Aprobación de prueba"), db, admin)
        policy.ejecutar(sid, db, admin)
        valid = {"respuesta_http_wompi": 200, "datos_confirmados": True, "transaction_id": "route-tx-001", "monto_centavos": 10000, "estado": "APPROVED"}
        monkeypatch.setattr(policy, "consultar_reembolso_sandbox", lambda _: valid)
        policy.verificar(sid, policy.ConsultaProveedor(refund_id="12345"), db, admin)
        monkeypatch.setattr(policy, "consultar_reembolso_sandbox", lambda _: {**valid, **changed})
        with pytest.raises(HTTPException) as exc:
            policy.verificar(sid, policy.ConsultaProveedor(refund_id="12345"), db, admin)
        assert exc.value.status_code == 409
        assert db.get(SolicitudReembolsoSandbox, sid).ejecucion == "CONFIRMADO"
        assert db.get(SolicitudReembolsoSandbox, sid).verificacion == "CONFIRMADO"
        assert db.query(AuditLog).filter_by(entidad_id=sid, accion="ALERTA_VERIFICACION_REEMBOLSO_SANDBOX").count() == 1
        assert db.query(CuotaAmortizacion).one().monto_pagado == Decimal("1250.00")
        assert db.query(Pago).count() == 1
    finally:
        db.close()


def test_respuesta_tardia_no_sobrescribe_estado_incierto(monkeypatch):
    db, admin = crear_pago(monkeypatch)
    calls = []
    try:
        request = policy.crear(nueva(wompi_pago_id=db.query(WompiPago).one().id), db, admin)
        sid = request["id"]
        policy.decidir(sid, policy.Decision(decision="APROBADA", justificacion="Aprobación de prueba"), db, admin)
        def delayed(**kwargs):
            calls.append(kwargs)
            with Session() as other:
                s = other.get(SolicitudReembolsoSandbox, sid)
                refund = other.get(WompiReembolsoSandbox, s.reembolso_id)
                s.ejecucion = refund.estado = "INCIERTO"
                other.commit()
            return {"status": "APPROVED", "refund_id": "12345"}
        monkeypatch.setattr(policy, "solicitar_reembolso_sandbox", delayed)
        with pytest.raises(HTTPException) as exc:
            policy.ejecutar(sid, db, admin)
        assert exc.value.status_code == 409
        db.expire_all()
        assert db.get(SolicitudReembolsoSandbox, sid).ejecucion == "INCIERTO"
        with pytest.raises(HTTPException):
            policy.ejecutar(sid, db, admin)
        assert len(calls) == 1 and db.query(CuotaAmortizacion).one().monto_pagado == Decimal("1250.00")
    finally:
        db.close()


@pytest.mark.parametrize("fase", ["antes_envio", "durante_envio"])
def test_interrupcion_conserva_reserva_tras_nueva_sesion(monkeypatch, fase):
    db, admin = crear_pago(monkeypatch)
    llamadas = []
    try:
        solicitud = policy.crear(nueva(wompi_pago_id=db.query(WompiPago).one().id), db, admin)
        sid, admin_id = solicitud["id"], admin.id
        policy.decidir(sid, policy.Decision(decision="APROBADA", justificacion="Validación sintética"), db, admin)
        def interrupcion(*args, **kwargs):
            llamadas.append(fase)
            raise SystemExit("interrupción simulada")
        if fase == "antes_envio":
            monkeypatch.setattr(policy, "consultar_transaccion", interrupcion)
        else:
            monkeypatch.setattr(policy, "solicitar_reembolso_sandbox", interrupcion)
        with pytest.raises(SystemExit):
            policy.ejecutar(sid, db, admin)
        db.close()
        with Session() as nueva_sesion:
            registrada = nueva_sesion.get(SolicitudReembolsoSandbox, sid)
            assert registrada.ejecucion == "CREANDO" and registrada.reembolso_id
            assert nueva_sesion.get(WompiReembolsoSandbox, registrada.reembolso_id).estado == "CREANDO"
            with pytest.raises(HTTPException):
                policy.ejecutar(sid, nueva_sesion, nueva_sesion.get(Usuario, admin_id))
            assert len(llamadas) == 1
            assert nueva_sesion.query(CuotaAmortizacion).one().monto_pagado == Decimal("1250.00")
    finally:
        db.close()
