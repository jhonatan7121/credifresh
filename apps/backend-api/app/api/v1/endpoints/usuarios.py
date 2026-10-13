from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.deps import RoleChecker
from app.core.security import get_password_hash
from app.models.usuario import Usuario
from modules.audit.audit_service import registrar_auditoria

router = APIRouter(
    prefix="/usuarios",
    tags=["Usuarios"]
)

# Whitelist explícita de roles gestionables por un administrador.
# El registro público (/auth/register) sigue creando únicamente CLIENTE.
RolGestionable = Literal["ADMIN", "GESTOR", "CLIENTE"]


class UsuarioGestionCreate(BaseModel):
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$", description="Email del usuario")
    password: str = Field(..., min_length=6, description="Contraseña del usuario (mínimo 6 caracteres)")
    rol: RolGestionable = Field(..., description="Rol a asignar: ADMIN, GESTOR o CLIENTE")


class CambioRolInput(BaseModel):
    rol: RolGestionable = Field(..., description="Nuevo rol: ADMIN, GESTOR o CLIENTE")


class UsuarioActivoInput(BaseModel):
    activo: bool = Field(..., description="True para reactivar, False para dar de baja lógica")


class UsuarioGestionResponse(BaseModel):
    id: int
    email: str
    rol: str
    activo: bool

    model_config = {"from_attributes": True}


@router.post("/", response_model=UsuarioGestionResponse, status_code=201)
def crear_usuario(
    usuario_in: UsuarioGestionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    """Crear un usuario con rol controlado. Solo ADMIN."""
    usuario_existente = (
        db.query(Usuario)
        .filter(Usuario.email == usuario_in.email)
        .first()
    )
    if usuario_existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El email ya está registrado"
        )

    nuevo_usuario = Usuario(
        email=usuario_in.email,
        password_hash=get_password_hash(usuario_in.password),
        rol=usuario_in.rol,
        activo=True,
    )
    db.add(nuevo_usuario)
    db.flush()
    registrar_auditoria(
        db=db,
        usuario=current_user,
        accion="CREAR_USUARIO",
        entidad="usuario",
        entidad_id=nuevo_usuario.id,
        detalles={"campos_registrados": ["email", "rol", "activo"]},
    )
    db.commit()
    db.refresh(nuevo_usuario)

    return nuevo_usuario


@router.patch("/{usuario_id}/rol", response_model=UsuarioGestionResponse)
def cambiar_rol_usuario(
    usuario_id: int,
    cambio_rol: CambioRolInput,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    """Asignar un nuevo rol a un usuario existente. Solo ADMIN."""
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).with_for_update().first()
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )

    if usuario.rol == cambio_rol.rol:
        return usuario

    if usuario.id == current_user.id and usuario.rol == "ADMIN" and cambio_rol.rol != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No puede cambiar su propio rol de ADMIN"
        )

    if usuario.activo and usuario.rol == "ADMIN" and cambio_rol.rol != "ADMIN":
        administradores_activos = (
            db.query(Usuario)
            .filter(Usuario.rol == "ADMIN", Usuario.activo.is_(True))
            .with_for_update()
            .all()
        )
        otros_administradores = [admin for admin in administradores_activos if admin.id != usuario.id]
        if not otros_administradores:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede cambiar el rol del último ADMIN activo"
            )

    rol_anterior = usuario.rol
    usuario.rol = cambio_rol.rol
    registrar_auditoria(
        db=db,
        usuario=current_user,
        accion="CAMBIAR_ROL_USUARIO",
        entidad="usuario",
        entidad_id=usuario.id,
        detalles={"rol_anterior": rol_anterior, "rol_nuevo": usuario.rol},
    )
    db.commit()
    db.refresh(usuario)

    return usuario


# ---------------------------------------------------------------------------
# H.2 — Consulta y ciclo de vida de usuarios (solo ADMIN)
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[UsuarioGestionResponse])
def listar_usuarios(
    rol: Optional[RolGestionable] = None,
    activo: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    """Listar usuarios con filtros opcionales por rol y estado. Solo ADMIN."""
    query = db.query(Usuario)
    if rol is not None:
        query = query.filter(Usuario.rol == rol)
    if activo is not None:
        query = query.filter(Usuario.activo == activo)
    return query.order_by(Usuario.id).all()


@router.get("/{usuario_id}", response_model=UsuarioGestionResponse)
def obtener_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    """Detalle de un usuario por id. Solo ADMIN."""
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    return usuario


@router.patch("/{usuario_id}/activo", response_model=UsuarioGestionResponse)
def cambiar_estado_usuario(
    usuario_id: int,
    cambio_activo: UsuarioActivoInput,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    """Activar o desactivar (baja lógica) un usuario. Solo ADMIN.

    Reglas de negocio:
    - No puede quedar la aplicación sin un ADMIN activo.
    - Un ADMIN no puede desactivar su propia cuenta.
    - La baja es lógica: la fila nunca se elimina.
    """
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )

    if not cambio_activo.activo and usuario.rol == "ADMIN" and usuario.activo:
        # Se evalúa antes que la autodesactivación para que, en el caso de
        # solape (objetivo == solicitante y último ADMIN), la regla de
        # integridad del rol ADMIN sea la que responda con 409.
        otro_admin_activo = (
            db.query(Usuario)
            .filter(
                Usuario.rol == "ADMIN",
                Usuario.activo.is_(True),
                Usuario.id != usuario.id,
            )
            .first()
        )
        if otro_admin_activo is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede desactivar al último ADMIN activo"
            )

    if not cambio_activo.activo and usuario.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No puede desactivar su propia cuenta"
        )

    if usuario.activo == cambio_activo.activo:
        return usuario

    estado_anterior = usuario.activo
    usuario.activo = cambio_activo.activo
    registrar_auditoria(
        db=db,
        usuario=current_user,
        accion="CAMBIAR_ESTADO_USUARIO",
        entidad="usuario",
        entidad_id=usuario.id,
        detalles={"estado_anterior": estado_anterior, "estado_nuevo": usuario.activo},
    )
    db.commit()
    db.refresh(usuario)
    return usuario
