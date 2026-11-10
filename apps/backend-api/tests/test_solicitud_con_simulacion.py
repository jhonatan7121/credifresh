from decimal import Decimal
import pytest
from fastapi import HTTPException

from app.core.deps import get_current_active_user
from app.models.aceptacion_credito import AceptacionCredito
from app.models.cliente import Cliente
from app.models.cotizacion_credito import CotizacionAceptada, TasaMensual
from app.models.credito import Credito
from app.models.perfil_financiero import PerfilFinanciero
from app.models.usuario import Usuario
from app.services.desembolso_wompi_sandbox import _validate_credit
from conftest import TestSessionLocal
from main import app
from app.api.v1.endpoints import creditos


def setup_customer():
    db = TestSessionLocal()
    user = Usuario(email="cotizacion-test@example.invalid", password_hash="no-login", rol="CLIENTE", activo=True)
    db.add(user)
    db.flush()
    customer = Cliente(nombre="Cliente simulado", cedula="989898989", telefono="3000000000", direccion="Calle de prueba 123", usuario_id=user.id)
    db.add(customer)
    db.flush()
    db.add(PerfilFinanciero(cliente_id=customer.id, ingresos_mensuales=5000000, gastos_mensuales=500000,
                            otras_obligaciones=0, tipo_ingresos="Prueba", actividad_economica="Prueba"))
    db.commit()
    db.refresh(user)
    user_id = user.id
    db.close()

    def customer_user():
        session = TestSessionLocal()
        try:
            return session.get(Usuario, user_id)
        finally:
            session.close()
    return customer_user


def payload(quote):
    return {key: quote[key] for key in ("monto", "plazo_meses", "mes_tasa", "tasa_interes", "cuota_mensual", "total_estimado")} | {"acepta": True}


def test_solicitud_con_condiciones_y_cambio_de_tasa(client, monkeypatch):
    # Administrador configura una tasa de prueba; no hay tasa predeterminada.
    vigente = client.get("/creditos/tasas-mensuales/vigente").json()
    mes = vigente["mes"]
    assert vigente["tasa_interes"] is None
    admin_override = app.dependency_overrides[get_current_active_user]
    customer_override = setup_customer()
    app.dependency_overrides[get_current_active_user] = customer_override
    assert client.post("/creditos/simular-solicitud", json={"monto": 500000, "plazo_meses": 1}).status_code == 503
    app.dependency_overrides[get_current_active_user] = admin_override
    assert client.put("/creditos/tasas-mensuales", json={"mes": "2000-01", "tasa_interes": "2"}).status_code == 400
    assert client.put("/creditos/tasas-mensuales", json={"mes": mes, "tasa_interes": "2.123"}).status_code == 422
    response = client.put("/creditos/tasas-mensuales", json={"mes": mes, "tasa_interes": "2.00"})
    assert response.status_code == 200
    app.dependency_overrides[get_current_active_user] = customer_override
    assert client.put("/creditos/tasas-mensuales", json={"mes": mes, "tasa_interes": "3.00"}).status_code == 403
    quote = client.post("/creditos/simular-solicitud", json={"monto": 500000, "plazo_meses": 1})
    assert quote.status_code == 200
    assert Decimal(quote.json()["cuota_mensual"]) == Decimal("510000.00")
    assert client.post("/creditos/mis", json={"monto": 500000, "plazo_meses": 1}).status_code == 422

    # Un cambio de tarifa invalida la pantalla anterior; no crea solicitud.
    app.dependency_overrides[get_current_active_user] = admin_override
    assert client.put("/creditos/tasas-mensuales", json={"mes": mes, "tasa_interes": "3.00"}).status_code == 200
    app.dependency_overrides[get_current_active_user] = customer_override
    assert client.post("/creditos/mis", json=payload(quote.json())).status_code == 409
    fresh = client.post("/creditos/simular-solicitud", json={"monto": 500000, "plazo_meses": 1}).json()
    assert Decimal(fresh["cuota_mensual"]) == Decimal("515000.00")
    ids = []
    for _ in range(2):
        response = client.post("/creditos/mis", json=payload(fresh))
        assert response.status_code == 201, response.text
        ids.append(response.json()["credito"]["id"])
    app.dependency_overrides[get_current_active_user] = admin_override
    assert client.patch(f"/creditos/{ids[0]}/tasa", json={"tasa_interes": "4.00"}).status_code == 200
    for credit_id in ids:
        response = client.post(f"/creditos/{credit_id}/evaluar")
        assert response.status_code == 200, response.text
        assert response.json()["decision"] == "APROBADO"
    db = TestSessionLocal()
    try:
        assert db.query(CotizacionAceptada).filter_by(credito_id=ids[0]).one().tasa_interes == Decimal("3.00")
        assert db.query(AceptacionCredito).filter_by(credito_id=ids[0]).first() is None
        assert db.query(AceptacionCredito).filter_by(credito_id=ids[1]).one().tasa_interes == Decimal("3.00")
        assert db.query(Credito).filter_by(id=ids[1]).one().estado == "APROBADO"
        assert _validate_credit(db, ids[1]).id == ids[1]
        with pytest.raises(HTTPException) as missing_acceptance:
            _validate_credit(db, ids[0])
        assert missing_acceptance.value.status_code == 409
    finally:
        db.close()
    # Si el administrador cambió la tasa, el cliente puede revisar y aceptar
    # la oferta final sin borrar la constancia de la simulación inicial.
    app.dependency_overrides[get_current_active_user] = customer_override
    loans = client.get("/creditos/mis").json()
    changed = next(loan for loan in loans if loan["credito"]["id"] == ids[0])
    final = {"acepta": True, "monto": changed["credito"]["monto"],
             "plazo_meses": changed["credito"]["plazo_meses"],
             "tasa_interes": changed["credito"]["tasa_interes"],
             "cuota_mensual": changed["evaluacion"]["cuota_mensual"],
             "total_estimado": changed["total_estimado"]}
    response = client.post(f"/creditos/{ids[0]}/aceptar", json=final)
    assert response.status_code == 201, response.text
    assert Decimal(str(response.json()["tasa_interes"])) == Decimal("4.00")
    # Al comenzar otro mes, la tasa sigue vigente hasta que se configure otra.
    year, month = map(int, mes.split("-"))
    siguiente = f"{year + (month == 12):04d}-{(month % 12) + 1:02d}"
    monkeypatch.setattr(creditos, "_mes_actual_colombia", lambda: siguiente)
    rollover = client.post("/creditos/simular-solicitud", json={"monto": 500000, "plazo_meses": 1})
    assert rollover.status_code == 200
    assert Decimal(rollover.json()["tasa_interes"]) == Decimal("3.00")
    assert rollover.json()["mes_tasa"] == mes
    app.dependency_overrides[get_current_active_user] = admin_override
    assert client.put("/creditos/tasas-mensuales", json={"mes": siguiente, "tasa_interes": "3.50"}).status_code == 200
    app.dependency_overrides[get_current_active_user] = customer_override
    assert client.post("/creditos/mis", json=payload(rollover.json())).status_code == 409
