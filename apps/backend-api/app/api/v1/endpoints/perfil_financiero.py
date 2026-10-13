from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.cliente import Cliente
from app.models.perfil_financiero import PerfilFinanciero
from app.core.deps import get_current_active_user, RoleChecker
from app.models.usuario import Usuario
from modules.audit.audit_service import registrar_auditoria

router = APIRouter(
    prefix="/clientes",
    tags=["Perfil Financiero"]
)


class PerfilFinancieroSchema(BaseModel):
    ingresos_mensuales: float = Field(gt=0)
    gastos_mensuales: float = Field(ge=0)
    otras_obligaciones: float = Field(ge=0)
    tipo_ingresos: str = Field(min_length=2, max_length=80)
    actividad_economica: str = Field(min_length=2, max_length=120)


@router.post("/{cliente_id}/perfil-financiero", status_code=201)
def crear_perfil_financiero(
    cliente_id: int,
    perfil_data: PerfilFinancieroSchema,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    # Si es CLIENTE, validar propiedad (IDOR)
    if current_user.rol == "CLIENTE":
        cliente_asociado = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
        if not cliente_asociado or cliente_asociado.id != cliente_id:
            raise HTTPException(
                status_code=403,
                detail="No tiene permisos para realizar esta operación sobre este cliente"
            )

    cliente = (
        db.query(Cliente)
        .filter(Cliente.id == cliente_id)
        .first()
    )

    if not cliente:
        raise HTTPException(
            status_code=404,
            detail="Cliente no encontrado"
        )

    perfil_existente = (
        db.query(PerfilFinanciero)
        .filter(PerfilFinanciero.cliente_id == cliente_id)
        .first()
    )

    if perfil_existente:
        raise HTTPException(
            status_code=409,
            detail="El cliente ya tiene un perfil financiero"
        )

    perfil = PerfilFinanciero(
        cliente_id=cliente_id,
        ingresos_mensuales=perfil_data.ingresos_mensuales,
        gastos_mensuales=perfil_data.gastos_mensuales,
        otras_obligaciones=perfil_data.otras_obligaciones,
        tipo_ingresos=perfil_data.tipo_ingresos,
        actividad_economica=perfil_data.actividad_economica
    )

    db.add(perfil)

    try:
        db.flush()
        registrar_auditoria(
            db=db,
            usuario=current_user,
            accion="CREAR_PERFIL_FINANCIERO",
            entidad="cliente",
            entidad_id=cliente_id,
            detalles={"campos_registrados": sorted(perfil_data.model_fields_set)},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="El cliente ya tiene un perfil financiero"
        )

    db.refresh(perfil)

    return {
        "mensaje": "Perfil financiero creado correctamente",
        "perfil_financiero": perfil
    }


@router.get("/{cliente_id}/perfil-financiero")
def obtener_perfil_financiero(
    cliente_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    # Si es CLIENTE, validar propiedad (IDOR)
    if current_user.rol == "CLIENTE":
        cliente_asociado = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
        if not cliente_asociado or cliente_asociado.id != cliente_id:
            raise HTTPException(
                status_code=403,
                detail="No tiene permisos para realizar esta operación sobre este cliente"
            )

    cliente = (
        db.query(Cliente)
        .filter(Cliente.id == cliente_id)
        .first()
    )

    if not cliente:
        raise HTTPException(
            status_code=404,
            detail="Cliente no encontrado"
        )

    perfil = (
        db.query(PerfilFinanciero)
        .filter(PerfilFinanciero.cliente_id == cliente_id)
        .first()
    )

    if not perfil:
        raise HTTPException(
            status_code=404,
            detail="Perfil financiero no encontrado"
        )

    return perfil


@router.put("/{cliente_id}/perfil-financiero")
def actualizar_perfil_financiero(
    cliente_id: int,
    perfil_data: PerfilFinancieroSchema,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    # Si es CLIENTE, solo puede actualizar el perfil de su propio cliente.
    if current_user.rol == "CLIENTE":
        cliente_asociado = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
        if not cliente_asociado or cliente_asociado.id != cliente_id:
            raise HTTPException(
                status_code=403,
                detail="No tiene permisos para realizar esta operación sobre este cliente"
            )

    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    perfil = db.query(PerfilFinanciero).filter(PerfilFinanciero.cliente_id == cliente_id).first()
    if not perfil:
        raise HTTPException(status_code=404, detail="Perfil financiero no encontrado")

    valores_nuevos = perfil_data.model_dump()
    campos_actualizados = [
        campo for campo, valor in valores_nuevos.items()
        if (
            Decimal(str(getattr(perfil, campo))) != Decimal(str(valor))
            if campo in {"ingresos_mensuales", "gastos_mensuales", "otras_obligaciones"}
            else getattr(perfil, campo) != valor
        )
    ]
    for campo, valor in valores_nuevos.items():
        setattr(perfil, campo, valor)

    if campos_actualizados:
        registrar_auditoria(
            db=db,
            usuario=current_user,
            accion="ACTUALIZAR_PERFIL_FINANCIERO",
            entidad="cliente",
            entidad_id=cliente_id,
            detalles={"campos_actualizados": campos_actualizados},
        )
    db.commit()
    db.refresh(perfil)
    return {
        "mensaje": "Perfil financiero actualizado correctamente",
        "perfil_financiero": perfil
    }
