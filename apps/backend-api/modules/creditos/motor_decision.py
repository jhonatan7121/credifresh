from dataclasses import dataclass


MONTO_MAXIMO = 1_500_000
PLAZO_MAXIMO_MESES = 12
PORCENTAJE_MAXIMO_CAPACIDAD = 0.40


@dataclass
class ResultadoDecision:
    decision: str
    motivos: list[str]
    cuota_mensual: float


def calcular_cuota_mensual(
    monto: float,
    plazo_meses: int,
    tasa_interes_mensual: float
) -> float:
    tasa = tasa_interes_mensual / 100

    if tasa == 0:
        return round(monto / plazo_meses, 2)

    cuota = (
        monto * tasa
        / (1 - (1 + tasa) ** (-plazo_meses))
    )

    return round(cuota, 2)


def evaluar_credito(
    monto: float,
    plazo_meses: int,
    capacidad_mensual: float,
    tasa_interes_mensual: float
) -> ResultadoDecision:
    aprobado = True
    motivos = []

    if monto > MONTO_MAXIMO:
        aprobado = False
        motivos.append(
            "El monto supera el máximo permitido"
        )

    if plazo_meses > PLAZO_MAXIMO_MESES:
        aprobado = False
        motivos.append(
            "El plazo supera el máximo permitido de 12 meses"
        )

    if capacidad_mensual <= 0:
        aprobado = False
        motivos.append(
            "El cliente no tiene capacidad financiera disponible"
        )

    cuota_mensual = calcular_cuota_mensual(
        monto=monto,
        plazo_meses=plazo_meses,
        tasa_interes_mensual=tasa_interes_mensual
    )

    capacidad_maxima_cuota = (
        capacidad_mensual * PORCENTAJE_MAXIMO_CAPACIDAD
    )

    if cuota_mensual > capacidad_maxima_cuota:
        aprobado = False
        motivos.append(
            "La cuota mensual supera el 40% de la capacidad financiera disponible"
        )

    if aprobado:
        decision = "APROBADO"
        motivos.append(
            "El crédito cumple las reglas básicas de evaluación"
        )
    else:
        decision = "RECHAZADO"

    return ResultadoDecision(
        decision=decision,
        motivos=motivos,
        cuota_mensual=cuota_mensual
    )