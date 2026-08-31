import datetime
from typing import List, Optional
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


@router.get("/", response_model=List[AuditLogResponse])
def listar_auditoria(
    usuario_id: Optional[int] = Query(default=None, gt=0),
    accion: Optional[str] = None,
    fecha_desde: Optional[datetime.datetime] = None,
    fecha_hasta: Optional[datetime.datetime] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["ADMIN"]))
):
    """
    Lista los registros de auditoría del sistema.
    Acceso exclusivo para el rol ADMIN. GESTOR y CLIENTE reciben 403.
    """
    query = db.query(AuditLog)

    if usuario_id is not None:
        query = query.filter(AuditLog.usuario_id == usuario_id)
    if accion is not None:
        query = query.filter(AuditLog.accion == accion)
    if fecha_desde is not None:
        query = query.filter(AuditLog.fecha_creacion >= fecha_desde)
    if fecha_hasta is not None:
        query = query.filter(AuditLog.fecha_creacion <= fecha_hasta)

    logs = query.order_by(AuditLog.fecha_creacion.desc()).all()
    return logs
