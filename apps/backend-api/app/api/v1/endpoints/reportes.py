from decimal import Decimal
from typing import Dict, Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.deps import get_current_active_user, RoleChecker
from app.models.usuario import Usuario
from modules.reportes.reportes_service import calcular_resumen_cartera, calcular_cartera_detalle

router = APIRouter(
    prefix="/reportes",
    tags=["Reportes Financieros"]
)


class ResumenCarteraResponse(BaseModel):
    total_clientes: int
    total_creditos: int
    creditos_por_estado: Dict[str, int]
    monto_total_solicitado: Decimal
    monto_total_desembolsado: Decimal
    monto_total_recaudado: Decimal

    model_config = {"from_attributes": True}


class CarteraDetalleResponse(BaseModel):
    cuotas_por_estado: Dict[str, int]
    saldo_pendiente_cartera: Decimal

    model_config = {"from_attributes": True}


@router.get("/resumen", response_model=ResumenCarteraResponse)
def obtener_resumen_cartera(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["GESTOR", "ADMIN"]))
):
    """
    Obtiene un resumen ejecutivo global de la cartera de clientes y créditos.
    Acceso exclusivo para roles GESTOR y ADMIN.
    """
    return calcular_resumen_cartera(db)


@router.get("/cartera", response_model=CarteraDetalleResponse)
def obtener_detalle_cartera(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["GESTOR", "ADMIN"]))
):
    """
    Obtiene el estado detallado de cuotas y saldos pendientes en la cartera.
    Acceso exclusivo para roles GESTOR y ADMIN.
    """
    return calcular_cartera_detalle(db)
