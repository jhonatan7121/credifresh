import datetime
from decimal import Decimal, ROUND_HALF_UP
from app.models.amortizacion import CuotaAmortizacion
from app.models.evaluacion import Evaluacion
from app.models.credito import Credito


def sumar_meses(fecha: datetime.datetime, meses: int) -> datetime.datetime:
    """
    Suma un número de meses consecutivo a una fecha, manejando correctamente 
    el desborde de días del mes (por ejemplo, de un 31 de enero a un 28/29 de febrero).
    """
    nuevo_mes = fecha.month + meses
    nuevo_ano = fecha.year + (nuevo_mes - 1) // 12
    nuevo_mes = (nuevo_mes - 1) % 12 + 1
    
    dia = fecha.day
    while True:
        try:
            return fecha.replace(year=nuevo_ano, month=nuevo_mes, day=dia)
        except ValueError:
            dia -= 1


def redondear(valor: Decimal) -> Decimal:
    """
    Redondea de forma precisa un valor monetario a 2 decimales utilizando ROUND_HALF_UP.
    """
    return valor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def generar_plan_amortizacion(
    credito: Credito,
    evaluacion: Evaluacion,
    fecha_desembolso: datetime.datetime
) -> list[CuotaAmortizacion]:
    """
    Genera el plan de amortización bajo el sistema francés para un crédito.
    La cuota mensual proviene de la evaluación física persistida del crédito, sin recalcularse.
    """
    monto_inicial = Decimal(str(credito.monto))
    cuota_fija = Decimal(str(evaluacion.cuota_mensual))
    tasa_mensual = Decimal(str(credito.tasa_interes)) / Decimal('100')
    plazo = credito.plazo_meses

    cuotas = []
    saldo_remanente = monto_inicial

    for i in range(1, plazo + 1):
        fecha_vencimiento = sumar_meses(fecha_desembolso, i)
        
        # Calcular el interés generado sobre el saldo remanente anterior
        interes_periodo = redondear(saldo_remanente * tasa_mensual)
        
        if i == plazo:
            # En la última cuota, el capital pagado es exactamente el saldo remanente actual
            capital_periodo = redondear(saldo_remanente)
            
            # NOTA IMPORTANTE DE NEGOCIO: La cuota total del último periodo se recalcula como la suma
            # del capital restante más el interés del periodo. Por tanto, puede diferir de la cuota
            # fija de Evaluacion únicamente por el ajuste de redondeo necesario para llevar
            # saldo_remanente exactamente a 0.00.
            cuota_periodo = redondear(capital_periodo + interes_periodo)
            nuevo_saldo = Decimal('0.00')
        else:
            # Abono a capital = Cuota fija menos interés del período
            capital_periodo = redondear(cuota_fija - interes_periodo)
            
            # Validación preventiva para no sobrepasar el saldo remanente
            if capital_periodo > saldo_remanente:
                capital_periodo = redondear(saldo_remanente)
                
            cuota_periodo = redondear(capital_periodo + interes_periodo)
            nuevo_saldo = redondear(saldo_remanente - capital_periodo)

        cuota_amort = CuotaAmortizacion(
            credito_id=credito.id,
            numero_cuota=i,
            fecha_vencimiento=fecha_vencimiento,
            monto_cuota=cuota_periodo,
            capital=capital_periodo,
            interes=interes_periodo,
            saldo_remanente=nuevo_saldo,
            monto_pagado=Decimal('0.00'),
            estado="PENDIENTE"
        )
        
        cuotas.append(cuota_amort)
        saldo_remanente = nuevo_saldo

    return cuotas
