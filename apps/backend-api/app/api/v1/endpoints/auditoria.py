import datetime
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.deps import RoleChecker
from app.models.usuario import Usuario
from app.models.audit_log import AuditLog

router = APIRouter(
    prefix="/auditoria",
    tags=["Auditoría"]
)


class AuditLogResponse(BaseModel):
    id: int
    usuario_id: Optional[int]
    rol: str
    accion: str
    entidad: str
    entidad_id: Optional[int]
    resultado: str
    detalles: Optional[str]
    ip: Optional[str]
    fecha_creacion: datetime.datetime

    model_config = {"from_attributes": True}


class AuditLogPageResponse(BaseModel):
    items: List[AuditLogResponse]
    total: int
    limit: int
    offset: int


def construir_consulta_auditoria(
    db: Session,
    usuario_id: Optional[int],
    accion: Optional[str],
    resultado: Optional[str],
    credito_id: Optional[int],
    fecha_desde: Optional[datetime.datetime],
    fecha_hasta: Optional[datetime.datetime],
    entidad: Optional[str] = None,
    entidad_id: Optional[int] = None,
    ip: Optional[str] = None,
):
    query = db.query(AuditLog)
    if usuario_id is not None:
        query = query.filter(AuditLog.usuario_id == usuario_id)
    if accion is not None:
        accion_escapada = accion.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(AuditLog.accion.ilike(f"%{accion_escapada}%", escape="\\"))
    if resultado is not None:
        query = query.filter(AuditLog.resultado == resultado)
    if credito_id is not None:
        query = query.filter(AuditLog.entidad == "credito", AuditLog.entidad_id == credito_id)
    if entidad is not None:
        query = query.filter(AuditLog.entidad == entidad)
    if entidad_id is not None:
        query = query.filter(AuditLog.entidad_id == entidad_id)
    if ip is not None:
        query = query.filter(AuditLog.ip == ip)
    if fecha_desde is not None:
        query = query.filter(AuditLog.fecha_creacion >= fecha_desde)
    if fecha_hasta is not None:
        query = query.filter(AuditLog.fecha_creacion <= fecha_hasta)
    return query


@router.get("/consulta", response_model=AuditLogPageResponse)
def consultar_auditoria_paginada(
    usuario_id: Optional[int] = Query(default=None, gt=0),
    accion: Optional[str] = None,
    resultado: Optional[str] = None,
    credito_id: Optional[int] = Query(default=None, gt=0),
    fecha_desde: Optional[datetime.datetime] = None,
    fecha_hasta: Optional[datetime.datetime] = None,
    entidad: Optional[Literal["credito", "cliente", "usuario"]] = None,
    entidad_id: Optional[int] = Query(default=None, gt=0),
    ip: Optional[str] = Query(default=None, min_length=1, max_length=45),
    limit: int = Query(default=50, gt=0, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    query = construir_consulta_auditoria(
        db, usuario_id, accion, resultado, credito_id, fecha_desde, fecha_hasta, entidad, entidad_id, ip
    )
    total = query.count()
    items = query.order_by(AuditLog.fecha_creacion.desc(), AuditLog.id.desc()).offset(offset).limit(limit).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/", response_model=List[AuditLogResponse])
def listar_auditoria(
    usuario_id: Optional[int] = Query(default=None, gt=0),
    accion: Optional[str] = None,
    resultado: Optional[str] = None,
    credito_id: Optional[int] = Query(default=None, gt=0),
    fecha_desde: Optional[datetime.datetime] = None,
    fecha_hasta: Optional[datetime.datetime] = None,
    entidad: Optional[Literal["credito", "cliente", "usuario"]] = None,
    entidad_id: Optional[int] = Query(default=None, gt=0),
    ip: Optional[str] = Query(default=None, min_length=1, max_length=45),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["ADMIN"]))
):
    """
    Lista los registros de auditoría del sistema.
    Acceso exclusivo para el rol ADMIN. GESTOR y CLIENTE reciben 403.
    """
    query = construir_consulta_auditoria(
        db, usuario_id, accion, resultado, credito_id, fecha_desde, fecha_hasta, entidad, entidad_id, ip
    )
    logs = query.order_by(AuditLog.fecha_creacion.desc(), AuditLog.id.desc()).all()
    return logs
