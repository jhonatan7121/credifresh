import pytest
from modules.creditos.motor_decision import (
    calcular_cuota_mensual,
    evaluar_credito,
    ResultadoDecision
)


def test_calcular_cuota_mensual_tasa_cero():
    """Prueba calcular_cuota_mensual con tasa 0%."""
    monto = 120000.0
    plazo_meses = 12
    tasa_interes_mensual = 0.0

    cuota = calcular_cuota_mensual(monto, plazo_meses, tasa_interes_mensual)
    assert cuota == 10000.0


def test_calcular_cuota_mensual_tasa_estandar():
    """Prueba calcular_cuota_mensual con una tasa de interés estándar (e.g. 2%)."""
    monto = 100000.0
    plazo_meses = 12
    tasa_interes_mensual = 2.0

    # Fórmula: (100000 * 0.02) / (1 - (1.02) ** -12)
    # 1.02 ** -12 = 0.788493175119438
    # 1 - 0.788493175119438 = 0.21150682488056196
    # 2000 / 0.21150682488056196 = 9455.959663675034
    # Redondeado a 2 decimales: 9455.96
    cuota = calcular_cuota_mensual(monto, plazo_meses, tasa_interes_mensual)
    assert cuota == 9455.96


def test_evaluacion_aprobada():
    """Prueba de evaluación aprobada bajo condiciones válidas."""
    monto = 1000000.0
    plazo_meses = 10
    capacidad_mensual = 500000.0
    tasa_interes_mensual = 2.0

    resultado = evaluar_credito(
        monto=monto,
        plazo_meses=plazo_meses,
        capacidad_mensual=capacidad_mensual,
        tasa_interes_mensual=tasa_interes_mensual
    )

    assert resultado.decision == "APROBADO"
    assert "El crédito cumple las reglas básicas de evaluación" in resultado.motivos
    assert len(resultado.motivos) == 1
    # 1000000 * 0.02 / (1 - 1.02 ** -10) = 20000 / (1 - 0.820348299) = 20000 / 0.1796517 = 111326.53
    assert resultado.cuota_mensual == 111326.53


def test_rechazo_monto_superior_maximo():
    """Prueba de rechazo por monto superior a $1.500.000."""
    monto = 1600000.0
    plazo_meses = 12
    capacidad_mensual = 500000.0
    tasa_interes_mensual = 2.0

    resultado = evaluar_credito(
        monto=monto,
        plazo_meses=plazo_meses,
        capacidad_mensual=capacidad_mensual,
        tasa_interes_mensual=tasa_interes_mensual
    )

    assert resultado.decision == "RECHAZADO"
    assert "El monto supera el máximo permitido" in resultado.motivos


def test_rechazo_plazo_superior_maximo():
    """Prueba de rechazo por plazo superior a 12 meses."""
    monto = 1000000.0
    plazo_meses = 13
    capacidad_mensual = 500000.0
    tasa_interes_mensual = 2.0

    resultado = evaluar_credito(
        monto=monto,
        plazo_meses=plazo_meses,
        capacidad_mensual=capacidad_mensual,
        tasa_interes_mensual=tasa_interes_mensual
    )

    assert resultado.decision == "RECHAZADO"
    assert "El plazo supera el máximo permitido de 12 meses" in resultado.motivos


def test_rechazo_capacidad_financiera_menor_o_igual_cero():
    """Prueba de rechazo por capacidad financiera menor o igual a cero (e.g. 0)."""
    monto = 1000000.0
    plazo_meses = 10
    capacidad_mensual = 0.0
    tasa_interes_mensual = 2.0

    resultado = evaluar_credito(
        monto=monto,
        plazo_meses=plazo_meses,
        capacidad_mensual=capacidad_mensual,
        tasa_interes_mensual=tasa_interes_mensual
    )

    assert resultado.decision == "RECHAZADO"
    assert "El cliente no tiene capacidad financiera disponible" in resultado.motivos


def test_rechazo_cuota_supera_porcentaje_capacidad():
    """Prueba de rechazo porque la cuota supera el 40% de la capacidad financiera."""
    # Cuota calculada para 1.000.000 a 10 meses al 2.0% es de 111.326,53.
    # Si la capacidad financiera es 150.000, el 40% es 60.000.
    # 111.326,53 supera 60.000.
    monto = 1000000.0
    plazo_meses = 10
    capacidad_mensual = 150000.0
    tasa_interes_mensual = 2.0

    resultado = evaluar_credito(
        monto=monto,
        plazo_meses=plazo_meses,
        capacidad_mensual=capacidad_mensual,
        tasa_interes_mensual=tasa_interes_mensual
    )

    assert resultado.decision == "RECHAZADO"
    assert "La cuota mensual supera el 40% de la capacidad financiera disponible" in resultado.motivos


def test_rechazo_acumulativo_multiples_reglas():
    """Prueba de rechazo acumulativo por múltiples reglas incumplidas."""
    # Incumple monto (> 1.500.000), plazo (> 12 meses), y capacidad <= 0.
    monto = 2000000.0
    plazo_meses = 15
    capacidad_mensual = -50000.0
    tasa_interes_mensual = 2.0

    resultado = evaluar_credito(
        monto=monto,
        plazo_meses=plazo_meses,
        capacidad_mensual=capacidad_mensual,
        tasa_interes_mensual=tasa_interes_mensual
    )

    assert resultado.decision == "RECHAZADO"
    assert "El monto supera el máximo permitido" in resultado.motivos
    assert "El plazo supera el máximo permitido de 12 meses" in resultado.motivos
    assert "El cliente no tiene capacidad financiera disponible" in resultado.motivos
    assert "La cuota mensual supera el 40% de la capacidad financiera disponible" in resultado.motivos
    assert len(resultado.motivos) == 4
