from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.cliente import Cliente as ClienteModel
from app.models.credito import Credito
from app.core.deps import get_current_active_user, RoleChecker
from app.models.usuario import Usuario

router = APIRouter(
    prefix="/clientes",
    tags=["Clientes"]
)


class ClienteSchema(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    cedula: str = Field(min_length=5, max_length=20, pattern=r"^\d+$")
    telefono: str = Field(min_length=7, max_length=20, pattern=r"^\+?\d+$")
    usuario_id: int | None = Field(default=None, description="ID del usuario asociado")


@router.get("/")
def listar_clientes(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["GESTOR", "ADMIN"]))
):
    clientes = db.query(ClienteModel).all()
    return clientes


@router.get("/{cliente_id}")
def obtener_cliente(
    cliente_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    # Si es CLIENTE, validar propiedad (IDOR)
    if current_user.rol == "CLIENTE":
        cliente_asociado = db.query(ClienteModel).filter(ClienteModel.usuario_id == current_user.id).first()
        if not cliente_asociado or cliente_asociado.id != cliente_id:
            raise HTTPException(
                status_code=403,
                detail="No tiene permisos para acceder a la información de este cliente"
            )

    cliente = (
        db.query(ClienteModel)
        .filter(ClienteModel.id == cliente_id)
        .first()
    )

    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    return cliente


@router.post("/", status_code=201)
def crear_cliente(
    cliente: ClienteSchema,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["GESTOR", "ADMIN"]))
):
    nuevo_cliente = ClienteModel(
        nombre=cliente.nombre,
        cedula=cliente.cedula,
        telefono=cliente.telefono,
        usuario_id=cliente.usuario_id
    )

    db.add(nuevo_cliente)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="La cédula ya está registrada"
        )

    db.refresh(nuevo_cliente)

    return {
        "mensaje": "Cliente creado correctamente",
        "cliente": nuevo_cliente
    }


@router.put("/{cedula}")
def actualizar_cliente(
    cedula: str,
    cliente_actualizado: ClienteSchema,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["GESTOR", "ADMIN"]))
):
    cliente = (
        db.query(ClienteModel)
        .filter(ClienteModel.cedula == cedula)
        .first()
    )

    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    cliente.nombre = cliente_actualizado.nombre
    cliente.cedula = cliente_actualizado.cedula
    cliente.telefono = cliente_actualizado.telefono
    if cliente_actualizado.usuario_id is not None:
        cliente.usuario_id = cliente_actualizado.usuario_id

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="La cédula ya está registrada"
        )

    db.refresh(cliente)

    return {
        "mensaje": "Cliente actualizado correctamente",
        "cliente": cliente
    }


@router.delete("/{cedula}")
def eliminar_cliente(
    cedula: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["ADMIN"]))
):
    cliente = (
        db.query(ClienteModel)
        .filter(ClienteModel.cedula == cedula)
        .first()
    )

    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    tiene_creditos = (
        db.query(Credito.id)
        .filter(Credito.cliente_id == cliente.id)
        .first()
    )

    if tiene_creditos:
        raise HTTPException(
            status_code=409,
            detail="No se puede eliminar un cliente con créditos asociados"
        )

    db.delete(cliente)
    db.commit()

    return {
        "mensaje": "Cliente eliminado correctamente",
        "cliente": {
            "id": cliente.id,
            "nombre": cliente.nombre,
            "cedula": cliente.cedula,
            "telefono": cliente.telefono
        }
    }

