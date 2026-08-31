from decimal import Decimal
from typing import List
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from modules.simulador.simulador_service import simular_credito

router = APIRouter(
    prefix="/simulador",
    tags=["Simulador"]
)


class SimuladorRequest(BaseModel):
    monto: Decimal = Field(..., gt=0, description="Monto del crédito")
    plazo_meses: int = Field(..., gt=0, description="Plazo en meses")
    tasa_interes: Decimal = Field(default=Decimal("2.0"), description="Tasa de interés mensual porcentaje")


class CuotaSimulacionResponse(BaseModel):
    numero_cuota: int
    monto_cuota: Decimal
    capital: Decimal
    interes: Decimal
    saldo_remanente: Decimal

    model_config = {"from_attributes": True}


class SimuladorResponse(BaseModel):
    monto: Decimal
    plazo_meses: int
    tasa_interes: Decimal
    cuota_mensual: Decimal
    total_intereses: Decimal
    total_pagar: Decimal
    amortizacion: List[CuotaSimulacionResponse]

    model_config = {"from_attributes": True}


@router.post("/credito", response_model=SimuladorResponse, status_code=status.HTTP_200_OK)
def simular_credito_endpoint(payload: SimuladorRequest):
    # Validar rangos de negocio
    if payload.monto < Decimal("500000.00") or payload.monto > Decimal("1500000.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El monto debe estar entre $500.000 y $1.500.000 COP"
        )

    if payload.plazo_meses < 1 or payload.plazo_meses > 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El plazo debe estar entre 1 y 12 meses"
        )

    if payload.tasa_interes < Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La tasa de interés no puede ser negativa"
        )

    resultado = simular_credito(
        monto=payload.monto,
        plazo_meses=payload.plazo_meses,
        tasa_interes=payload.tasa_interes
    )

    return resultado
