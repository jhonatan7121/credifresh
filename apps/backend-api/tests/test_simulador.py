import pytest
from fastapi.testclient import TestClient
from decimal import Decimal
from conftest import TestSessionLocal
from app.models.audit_log import AuditLog
from app.models.notificacion import Notificacion
from app.models.credito import Credito
from app.models.cliente import Cliente


def test_simulador_valido(client: TestClient):
    """1. Simulación válida y 2. Acceso público sin JWT."""
    resp = client.post("/simulador/credito", json={
        "monto": 1000000.0,
        "plazo_meses": 10,
        "tasa_interes": 2.0
    })
    assert resp.status_code == 200
    data = resp.json()
    assert Decimal(str(data["monto"])) == Decimal("1000000.00")
    assert data["plazo_meses"] == 10
    assert len(data["amortizacion"]) == 10


def test_simulador_monto_minimo(client: TestClient):
    """3. Monto mínimo ($500.000)."""
    resp = client.post("/simulador/credito", json={
        "monto": 500000.0,
        "plazo_meses": 6,
        "tasa_interes": 2.0
    })
    assert resp.status_code == 200
    assert Decimal(str(resp.json()["monto"])) == Decimal("500000.00")


def test_simulador_monto_maximo(client: TestClient):
    """4. Monto máximo ($1.500.000)."""
    resp = client.post("/simulador/credito", json={
        "monto": 1500000.0,
        "plazo_meses": 12,
        "tasa_interes": 2.0
    })
    assert resp.status_code == 200
    assert Decimal(str(resp.json()["monto"])) == Decimal("1500000.00")


def test_simulador_monto_inferior_al_minimo(client: TestClient):
    """5. Monto inferior al mínimo (< $500.000 -> 400)."""
    resp = client.post("/simulador/credito", json={
        "monto": 400000.0,
        "plazo_meses": 6,
        "tasa_interes": 2.0
    })
    assert resp.status_code == 400
    assert "El monto debe estar entre" in resp.json()["detail"]


def test_simulador_monto_superior_al_maximo(client: TestClient):
    """6. Monto superior al máximo (> $1.500.000 -> 400)."""
    resp = client.post("/simulador/credito", json={
        "monto": 1600000.0,
        "plazo_meses": 6,
        "tasa_interes": 2.0
    })
    assert resp.status_code == 400
    assert "El monto debe estar entre" in resp.json()["detail"]


def test_simulador_plazo_minimo(client: TestClient):
    """7. Plazo mínimo (1 mes)."""
    resp = client.post("/simulador/credito", json={
        "monto": 1000000.0,
        "plazo_meses": 1,
        "tasa_interes": 2.0
    })
    assert resp.status_code == 200
    assert resp.json()["plazo_meses"] == 1
    assert len(resp.json()["amortizacion"]) == 1


def test_simulador_plazo_maximo(client: TestClient):
    """8. Plazo máximo (12 meses)."""
    resp = client.post("/simulador/credito", json={
        "monto": 1000000.0,
        "plazo_meses": 12,
        "tasa_interes": 2.0
    })
    assert resp.status_code == 200
    assert resp.json()["plazo_meses"] == 12


def test_simulador_plazo_superior_al_maximo(client: TestClient):
    """9. Plazo superior al máximo (> 12 -> 400)."""
    resp = client.post("/simulador/credito", json={
        "monto": 1000000.0,
        "plazo_meses": 13,
        "tasa_interes": 2.0
    })
    assert resp.status_code == 400
    assert "El plazo debe estar entre" in resp.json()["detail"]


def test_simulador_plazo_invalido(client: TestClient):
    """10. Plazo inválido (cero o negativo -> 422 o 400)."""
    resp = client.post("/simulador/credito", json={
        "monto": 1000000.0,
        "plazo_meses": 0,
        "tasa_interes": 2.0
    })
    assert resp.status_code in [400, 422]


def test_simulador_tasa_invalida(client: TestClient):
    """11. Tasa inválida (negativa -> 400)."""
    resp = client.post("/simulador/credito", json={
        "monto": 1000000.0,
        "plazo_meses": 6,
        "tasa_interes": -1.0
    })
    assert resp.status_code == 400
    assert "La tasa de interés no puede ser negativa" in resp.json()["detail"]


def test_simulador_precision_decimal_y_amortizacion(client: TestClient):
    """12, 13, 14, 15, 16, 17, 18. Precisión Decimal, tabla amortización, saldo final 0.00, última cuota, suma capital, intereses y total a pagar."""
    resp = client.post("/simulador/credito", json={
        "monto": 1200000.0,
        "plazo_meses": 8,
        "tasa_interes": 1.5
    })
    assert resp.status_code == 200
    data = resp.json()

    monto_inicial = Decimal(str(data["monto"]))
    suma_capital = sum(Decimal(str(c["capital"])) for c in data["amortizacion"])
    suma_intereses = sum(Decimal(str(c["interes"])) for c in data["amortizacion"])
    total_pagar = Decimal(str(data["total_pagar"]))
    total_intereses = Decimal(str(data["total_intereses"]))

    assert suma_capital == monto_inicial
    assert suma_intereses == total_intereses
    assert total_pagar == monto_inicial + total_intereses
    assert Decimal(str(data["amortizacion"][-1]["saldo_remanente"])) == Decimal("0.00")


def test_simulador_ausencia_persistencia(client: TestClient):
    """19. Ausencia absoluta de persistencia en base de datos."""
    db = TestSessionLocal()
    try:
        creditos_antes = db.query(Credito).count()
        clientes_antes = db.query(Cliente).count()
        notif_antes = db.query(Notificacion).count()
        audit_antes = db.query(AuditLog).count()
    finally:
        db.close()

    resp = client.post("/simulador/credito", json={
        "monto": 1000000.0,
        "plazo_meses": 6,
        "tasa_interes": 2.0
    })
    assert resp.status_code == 200

    db = TestSessionLocal()
    try:
        assert db.query(Credito).count() == creditos_antes
        assert db.query(Cliente).count() == clientes_antes
        assert db.query(Notificacion).count() == notif_antes
        assert db.query(AuditLog).count() == audit_antes
    finally:
        db.close()


def test_simulador_payload_invalido(client: TestClient):
    """20. Payload inválido (422)."""
    resp = client.post("/simulador/credito", json={
        "monto": "no-es-un-numero",
        "plazo_meses": 6
    })
    assert resp.status_code == 422
