from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.usuario import Usuario as UsuarioModel
from app.core.security import get_password_hash, verify_password, create_access_token

router = APIRouter(
    prefix="/auth",
    tags=["Autenticación"]
)

# Esquemas Pydantic
class UsuarioCreate(BaseModel):
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$", description="Email del usuario")
    password: str = Field(..., min_length=6, description="Contraseña del usuario (mínimo 6 caracteres)")
    rol: str = Field(default="CLIENTE", description="Rol del usuario")

class UsuarioLogin(BaseModel):
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")
    password: str = Field(..., min_length=6)

class UsuarioResponse(BaseModel):
    id: int
    email: str
    rol: str
    activo: bool

    model_config = {"from_attributes": True}

class TokenResponse(BaseModel):
    access_token: str
    token_type: str


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
        raise HTTPException(
            status_code=401,
            detail="Credenciales incorrectas"
        )
        
    # Verificar contraseña
    if not verify_password(credenciales.password, usuario.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Credenciales incorrectas"
        )
        
    # Verificar que el usuario esté activo
    if not usuario.activo:
        raise HTTPException(
            status_code=400,
            detail="El usuario está inactivo"
        )
        
    # Generar JWT
    access_token = create_access_token(data={"sub": usuario.email, "rol": usuario.rol})
    
    return {
        "access_token": access_token,
        "token_type": "bearer"
    }
