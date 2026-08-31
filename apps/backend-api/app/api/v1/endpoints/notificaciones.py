import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.notificacion import Notificacion
from app.models.usuario import Usuario
from app.core.deps import get_current_active_user, RoleChecker

router = APIRouter(
    prefix="/notificaciones",
    tags=["Notificaciones"]
)


class NotificacionResponse(BaseModel):
    id: int
    usuario_id: int
    credito_id: Optional[int] = None
    titulo: str
    mensaje: str
    leida: bool
    fecha_creacion: datetime.datetime

    model_config = {"from_attributes": True}


@router.get("/", response_model=List[NotificacionResponse])
def listar_notificaciones(
    leida: Optional[bool] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    query = db.query(Notificacion)

    if current_user.rol == "CLIENTE":
        query = query.filter(Notificacion.usuario_id == current_user.id)
    elif current_user.rol in ["GESTOR", "ADMIN"]:
        pass
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autorizado para consultar notificaciones"
        )

    if leida is not None:
        query = query.filter(Notificacion.leida == leida)

    return query.order_by(Notificacion.fecha_creacion.desc()).all()


@router.patch("/{notificacion_id}/leer", response_model=NotificacionResponse)
def marcar_notificacion_leida(
    notificacion_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    notificacion = db.query(Notificacion).filter(Notificacion.id == notificacion_id).first()
    if not notificacion:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")

    if current_user.rol == "CLIENTE" and notificacion.usuario_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autorizado para modificar esta notificación"
        )

    notificacion.leida = True
    db.commit()
    db.refresh(notificacion)
    return notificacion