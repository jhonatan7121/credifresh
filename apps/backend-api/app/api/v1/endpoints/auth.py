import logging
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.usuario import Usuario as UsuarioModel
from app.core.security import ALGORITHM, SECRET_KEY, get_password_hash, verify_password, create_access_token
from app.core.deps import get_current_active_user
from modules.audit.audit_service import registrar_auditoria

router = APIRouter(
    prefix="/auth",
    tags=["Autenticación"]
)
logger = logging.getLogger(__name__)

# Esquemas Pydantic
class UsuarioCreate(BaseModel):
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$", description="Email del usuario")
    password: str = Field(..., min_length=6, description="Contraseña del usuario (mínimo 6 caracteres)")
    rol: str = Field(default="CLIENTE", description="Rol del usuario")

class UsuarioLogin(BaseModel):
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")
    password: str = Field(..., min_length=6)


class PasswordResetRequest(BaseModel):
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")


class PasswordResetComplete(BaseModel):
    token: str = Field(min_length=20)
    password: str = Field(min_length=8, max_length=72)


def _send_password_reset_email(email: str, reset_url: str) -> None:
    try:
        message = EmailMessage()
        message["Subject"] = "Restablece tu contraseña de CrediFresh"
        message["From"] = os.getenv("SMTP_FROM_EMAIL") or os.getenv("SMTP_USERNAME", "")
        message["To"] = email
        message.set_content(
            "Recibimos una solicitud para cambiar la contraseña de tu cuenta CrediFresh. "
            "Abre este enlace para elegir una nueva contraseña. El enlace vence en 20 minutos y "
            "solo puede usarse una vez. Si no solicitaste este cambio, ignora este mensaje.\n\n"
            f"{reset_url}\n"
        )
        host = os.getenv("SMTP_HOST")
        port = int(os.getenv("SMTP_PORT", "587"))
        username = os.getenv("SMTP_USERNAME")
        password = os.getenv("SMTP_PASSWORD")
        use_ssl = os.getenv("SMTP_USE_SSL", "false").lower() in {"1", "true", "yes"}
        client = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with client(host, port, timeout=15) as server:
            if not use_ssl:
                server.starttls()
            if username:
                server.login(username, password or "")
            server.send_message(message)
    except Exception:
        logger.exception("No se pudo entregar un correo de recuperación de contraseña")

class UsuarioResponse(BaseModel):
    id: int
    email: str
    rol: str
    activo: bool

    model_config = {"from_attributes": True}

class TokenResponse(BaseModel):
    access_token: str
    token_type: str


@router.get("/me", response_model=UsuarioResponse)
def obtener_sesion_actual(
    current_user: UsuarioModel = Depends(get_current_active_user),
):
    return current_user


@router.post("/password-reset/request", status_code=202)
def solicitar_restablecimiento_contrasena(
    request: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    smtp_host = os.getenv("SMTP_HOST")
    reset_base_url = os.getenv("RESET_PASSWORD_URL")
    if not smtp_host or not reset_base_url or not (os.getenv("SMTP_FROM_EMAIL") or os.getenv("SMTP_USERNAME")):
        raise HTTPException(status_code=503, detail="El servicio de recuperación por correo todavía no está configurado")

    generic_response = {"mensaje": "Si existe una cuenta activa con ese correo, enviaremos un enlace de recuperación."}
    usuario = db.query(UsuarioModel).filter(UsuarioModel.email == request.email.strip(), UsuarioModel.activo.is_(True)).first()
    if not usuario:
        return generic_response

    issued_at = datetime.now(timezone.utc)
    usuario.password_reset_issued_at = issued_at
    db.commit()
    token = jwt.encode(
        {"sub": usuario.email, "purpose": "password_reset", "iat": int(issued_at.timestamp()), "exp": issued_at + timedelta(minutes=20)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    separator = "&" if "?" in reset_base_url else "?"
    reset_url = f"{reset_base_url}{separator}{urlencode({'token': token})}"
    background_tasks.add_task(_send_password_reset_email, usuario.email, reset_url)
    return generic_response


@router.post("/password-reset/confirm")
def confirmar_restablecimiento_contrasena(
    request: PasswordResetComplete,
    db: Session = Depends(get_db),
):
    try:
        payload = jwt.decode(request.token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("purpose") != "password_reset" or not payload.get("sub"):
            raise JWTError("Token de recuperación inválido")
        email = payload["sub"]
        issued_at = int(payload["iat"])
    except (JWTError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="El enlace de recuperación venció o no es válido")

    usuario = db.query(UsuarioModel).filter(UsuarioModel.email == email, UsuarioModel.activo.is_(True)).first()
    saved_issued_at = usuario.password_reset_issued_at if usuario else None
    if not usuario or not saved_issued_at or int(saved_issued_at.timestamp()) != issued_at:
        raise HTTPException(status_code=400, detail="El enlace de recuperación venció o ya fue utilizado")

    usuario.password_hash = get_password_hash(request.password)
    usuario.password_reset_issued_at = None
    usuario.auth_token_version += 1
    registrar_auditoria(db=db, usuario=usuario, accion="RESTABLECER_CONTRASENA", entidad="usuario", entidad_id=usuario.id, resultado="EXITOSO")
    db.commit()
    return {"mensaje": "Contraseña actualizada. Ya puedes iniciar sesión."}


@router.post("/register", response_model=UsuarioResponse, status_code=201)
def registrar_usuario(
    usuario_in: UsuarioCreate,
    db: Session = Depends(get_db)
):
    # Validar que el email no exista
    usuario_existente = (
        db.query(UsuarioModel)
        .filter(UsuarioModel.email == usuario_in.email)
        .first()
    )
    if usuario_existente:
        raise HTTPException(
            status_code=409,
            detail="El email ya está registrado"
        )
    
    # Generar password_hash
    hashed_password = get_password_hash(usuario_in.password)
    
    # Crear Usuario
    nuevo_usuario = UsuarioModel(
        email=usuario_in.email,
        password_hash=hashed_password,
        rol="CLIENTE",  # Forzar siempre el rol CLIENTE en registro público
        activo=True
    )
    
    db.add(nuevo_usuario)
    db.flush()
    registrar_auditoria(
        db=db,
        usuario=nuevo_usuario,
        accion="REGISTRO_PUBLICO_CLIENTE",
        entidad="usuario",
        entidad_id=nuevo_usuario.id,
        detalles={"campos_registrados": ["email", "rol", "activo"]},
    )
    db.commit()
    db.refresh(nuevo_usuario)
    
    return nuevo_usuario


@router.post("/login", response_model=TokenResponse)
def login_usuario(
    credenciales: UsuarioLogin,
    db: Session = Depends(get_db)
):
    # Buscar usuario
    usuario = (
        db.query(UsuarioModel)
        .filter(UsuarioModel.email == credenciales.email)
        .first()
    )
    
    if not usuario:
        registrar_auditoria(
            db=db,
            usuario=None,
            accion="INICIO_SESION_FALLIDO",
            entidad="usuario",
            entidad_id=None,
            resultado="FALLIDO",
            detalles={"motivo": "CREDENCIALES_INVALIDAS"},
        )
        db.commit()
        raise HTTPException(
            status_code=401,
            detail="Credenciales incorrectas"
        )
        
    # Verificar contraseña
    if not verify_password(credenciales.password, usuario.password_hash):
        registrar_auditoria(
            db=db,
            usuario=usuario,
            accion="INICIO_SESION_FALLIDO",
            entidad="usuario",
            entidad_id=usuario.id,
            resultado="FALLIDO",
            detalles={"motivo": "CREDENCIALES_INVALIDAS"},
        )
        db.commit()
        raise HTTPException(
            status_code=401,
            detail="Credenciales incorrectas"
        )
        
    # Verificar que el usuario esté activo
    if not usuario.activo:
        registrar_auditoria(
            db=db,
            usuario=usuario,
            accion="INICIO_SESION_BLOQUEADO",
            entidad="usuario",
            entidad_id=usuario.id,
            resultado="BLOQUEADO",
            detalles={"motivo": "CUENTA_INACTIVA"},
        )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="El usuario está inactivo"
        )

    registrar_auditoria(
        db=db,
        usuario=usuario,
        accion="INICIO_SESION",
        entidad="usuario",
        entidad_id=usuario.id,
        resultado="EXITOSO",
        detalles={"resultado": "AUTENTICADO"},
    )
    db.commit()
        
    # Generar JWT
    access_token = create_access_token(data={"sub": usuario.email, "rol": usuario.rol, "purpose": "access", "tv": usuario.auth_token_version})
    
    return {
        "access_token": access_token,
        "token_type": "bearer"
    }
