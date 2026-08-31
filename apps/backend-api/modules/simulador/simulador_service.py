from decimal import Decimal, ROUND_HALF_UP, Context, FloatOperation

def redondear(valor: Decimal) -> Decimal:
    """Redondea estrictamente utilizando ROUND_HALF_UP a 2 decimales."""
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_cuota_mensual_decimal(
    monto: Decimal,
    plazo_meses: int,
    tasa_interes_mensual: Decimal
) -> Decimal:
    """Calcula la cuota mensual fija usando precisión Decimal y sistema francés.

    Fórmula: C = P * [ i / (1 - (1 + i)^(-n)) ]
    """
    tasa = tasa_interes_mensual / Decimal("100")

    if tasa == Decimal("0"):
        return redondear(monto / Decimal(str(plazo_meses)))

    # Para evitar errores de precisión con exponente flotante, convertimos a float temporalmente
    # sólo para el cálculo de potencia matemática, luego inmediato a Decimal.
    # Alternativa puramente Decimal usando Context con FloatOperation desactivado o math:
    # Usamos float() para la potencia (1 + i)**(-n) ya que Python no tiene un operador nativo de potencia Decimal fraccional en float,
    # pero multiplicamos y redondeamos estrictamente como Decimal.
    factor = Decimal(str((1 + float(tasa)) ** (-plazo_meses)))
    denominador = Decimal("1") - factor
    if denominador == Decimal("0"):
        return redondear(monto / Decimal(str(plazo_meses)))

    cuota = (monto * tasa) / denominador
    return redondear(cuota)


def simular_credito(
    monto: Decimal,
    plazo_meses: int,
    tasa_interes: Decimal
):
    """Genera la simulación completa del crédito y su tabla de amortización preliminar en memoria."""
    cuota_mensual = calcular_cuota_mensual_decimal(monto, plazo_meses, tasa_interes)
    tasa_mensual = tasa_interes / Decimal("100")

    amortizacion = []
    saldo_remanente = monto
    total_intereses = Decimal("0.00")
    suma_capital = Decimal("0.00")

    for i in range(1, plazo_meses + 1):
        interes_periodo = redondear(saldo_remanente * tasa_mensual)
        total_intereses += interes_periodo

        if i == plazo_meses:
            # En la última cuota, todo el saldo remanente restante va a capital
            capital_periodo = redondear(saldo_remanente)
            cuota_periodo = redondear(capital_periodo + interes_periodo)
            nuevo_saldo = Decimal("0.00")
        else:
            capital_periodo = redondear(cuota_mensual - interes_periodo)
            if capital_periodo > saldo_remanente:
                capital_periodo = redondear(saldo_remanente)
            cuota_periodo = redondear(capital_periodo + interes_periodo)
            nuevo_saldo = redondear(saldo_remanente - capital_periodo)

        suma_capital += capital_periodo

        amortizacion.append({
            "numero_cuota": i,
            "monto_cuota": cuota_periodo,
            "capital": capital_periodo,
            "interes": interes_periodo,
            "saldo_remanente": nuevo_saldo
        })

        saldo_remanente = nuevo_saldo

    # Ajuste por diferencia de centavos en la última cuota si la suma de capital difiere del monto inicial
    diferencia_capital = monto - suma_capital
    if diferencia_capital != Decimal("0.00") and len(amortizacion) > 0:
        # Ajustar la última cuota
        ultima = amortizacion[-1]
        ultima["capital"] = redondear(ultima["capital"] + diferencia_capital)
        ultima["monto_cuota"] = redondear(ultima["capital"] + ultima["interes"])
        suma_capital += diferencia_capital

    total_pagar = redondear(monto + total_intereses)

    return {
        "monto": redondear(monto),
        "plazo_meses": plazo_meses,
        "tasa_interes": redondear(tasa_interes),
        "cuota_mensual": cuota_mensual,
        "total_intereses": redondear(total_intereses),
        "total_pagar": total_pagar,
        "amortizacion": amortizacion
    }
