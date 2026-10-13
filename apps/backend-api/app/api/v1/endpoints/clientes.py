from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.cliente import Cliente as ClienteModel
from app.models.credito import Credito
from app.core.deps import get_current_active_user, RoleChecker
from app.models.usuario import Usuario
from modules.audit.audit_service import registrar_auditoria

router = APIRouter(
    prefix="/clientes",
    tags=["Clientes"]
)


class ClienteSchema(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    cedula: str = Field(min_length=5, max_length=20, pattern=r"^\d+$")
    telefono: str = Field(min_length=7, max_length=20, pattern=r"^\+?\d+$")
    direccion: str | None = Field(default=None, max_length=240)
    email: str | None = Field(default=None, min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    usuario_id: int | None = Field(default=None, description="ID del usuario asociado")


class ClienteContactoSchema(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    cedula: str = Field(min_length=5, max_length=20, pattern=r"^\d+$")
    telefono: str = Field(min_length=7, max_length=20, pattern=r"^\+?\d+$")
    direccion: str | None = Field(default=None, max_length=240)
    email: str | None = Field(default=None, min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MiContactoSchema(BaseModel):
    telefono: str = Field(min_length=7, max_length=20, pattern=r"^\+?\d+$")
    direccion: str = Field(min_length=5, max_length=240)


class VincularUsuarioInput(BaseModel):
    usuario_id: int = Field(gt=0)


@router.patch("/{cliente_id}/vincular-usuario")
def vincular_usuario_cliente(
    cliente_id: int,
    vinculo: VincularUsuarioInput,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["ADMIN"])),
):
    cliente = (
        db.query(ClienteModel)
        .filter(ClienteModel.id == cliente_id)
        .with_for_update()
        .first()
    )
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    if cliente.usuario_id is not None:
        if cliente.usuario_id == vinculo.usuario_id:
            return {"mensaje": "La cuenta ya está vinculada", "cliente": cliente}
        raise HTTPException(status_code=409, detail="El cliente ya tiene una cuenta vinculada")

    usuario = db.query(Usuario).filter(Usuario.id == vinculo.usuario_id).first()
    if not usuario or usuario.rol != "CLIENTE" or not usuario.activo:
        raise HTTPException(status_code=400, detail="Selecciona una cuenta CLIENTE activa")

    ya_vinculado = db.query(ClienteModel.id).filter(ClienteModel.usuario_id == usuario.id).first()
    if ya_vinculado:
        raise HTTPException(status_code=409, detail="La cuenta ya está vinculada a otro cliente")

    cliente.usuario_id = usuario.id
    registrar_auditoria(
        db=db,
        usuario=current_user,
        accion="VINCULAR_CUENTA_CLIENTE",
        entidad="cliente",
        entidad_id=cliente.id,
        detalles={"campos_actualizados": ["usuario_id"]},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="La cuenta ya está vinculada a otro cliente")

    db.refresh(cliente)
    return {"mensaje": "Cuenta de cliente vinculada correctamente", "cliente": cliente}


@router.get("/")
def listar_clientes(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["GESTOR", "ADMIN"]))
):
    clientes = db.query(ClienteModel).all()
    return clientes


@router.patch("/{cliente_id}")
def actualizar_datos_contacto_cliente(
    cliente_id: int,
    datos: ClienteContactoSchema,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["GESTOR", "ADMIN"])),
):
    cliente = db.query(ClienteModel).filter(ClienteModel.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    campos_actualizados = [
        campo for campo in ("nombre", "cedula", "telefono", "email")
        if getattr(cliente, campo) != getattr(datos, campo)
    ]
    if "direccion" in datos.model_fields_set and cliente.direccion != datos.direccion:
        campos_actualizados.append("direccion")
    cliente.nombre = datos.nombre
    cliente.cedula = datos.cedula
    cliente.telefono = datos.telefono
    if "direccion" in datos.model_fields_set:
        cliente.direccion = datos.direccion
    cliente.email = datos.email
    try:
        if campos_actualizados:
            registrar_auditoria(
                db=db,
                usuario=current_user,
                accion="ACTUALIZAR_CONTACTO_CLIENTE",
                entidad="cliente",
                entidad_id=cliente.id,
                detalles={"campos_actualizados": campos_actualizados},
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="La cédula ya está registrada")

    db.refresh(cliente)
    return {"mensaje": "Datos de contacto actualizados correctamente", "cliente": cliente}


@router.get("/me")
def obtener_mi_perfil_cliente(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["CLIENTE"])),
):
    """Return only the profile associated with the authenticated client account."""
    cliente = (
        db.query(ClienteModel)
        .filter(ClienteModel.usuario_id == current_user.id)
        .first()
    )
    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu cuenta aún no está vinculada a un perfil de cliente",
        )
    return {
        "id": cliente.id,
        "nombre": cliente.nombre,
        "email": cliente.email,
        "telefono": cliente.telefono,
        "direccion": cliente.direccion,
    }


@router.put("/me/contacto")
def actualizar_mi_contacto_cliente(
    datos: MiContactoSchema,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["CLIENTE"])),
):
    cliente = db.query(ClienteModel).filter(ClienteModel.usuario_id == current_user.id).first()
    if not cliente:
        raise HTTPException(status_code=403, detail="Tu cuenta aún no está vinculada a un perfil de cliente")
    cambios = []
    for campo in ("telefono", "direccion"):
        valor = getattr(datos, campo)
        if getattr(cliente, campo) != valor:
            cambios.append(campo)
            setattr(cliente, campo, valor)
    if cambios:
        registrar_auditoria(db=db, usuario=current_user, accion="ACTUALIZAR_CONTACTO_PROPIO", entidad="cliente", entidad_id=cliente.id, detalles={"campos_actualizados": cambios})
        db.commit()
        db.refresh(cliente)
    return {"mensaje": "Datos de contacto actualizados correctamente", "telefono": cliente.telefono, "direccion": cliente.direccion}


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
        direccion=cliente.direccion,
        email=cliente.email,
        usuario_id=cliente.usuario_id
    )

    db.add(nuevo_cliente)
    try:
        db.flush()
        registrar_auditoria(
            db=db,
            usuario=current_user,
            accion="CREAR_CLIENTE",
            entidad="cliente",
            entidad_id=nuevo_cliente.id,
            detalles={
                "campos_registrados": [
                    "nombre", "cedula", "telefono", "direccion", "email",
                    *(["usuario_id"] if nuevo_cliente.usuario_id is not None else []),
                ]
            },
        )
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

    campos_actualizados = []
    campos = [
        ("nombre", cliente_actualizado.nombre),
        ("cedula", cliente_actualizado.cedula),
        ("telefono", cliente_actualizado.telefono),
    ]
    if "direccion" in cliente_actualizado.model_fields_set:
        campos.append(("direccion", cliente_actualizado.direccion))
    for campo, nuevo_valor in campos:
        if getattr(cliente, campo) != nuevo_valor:
            campos_actualizados.append(campo)
    cliente.nombre = cliente_actualizado.nombre
    cliente.cedula = cliente_actualizado.cedula
    cliente.telefono = cliente_actualizado.telefono
    if "direccion" in cliente_actualizado.model_fields_set:
        cliente.direccion = cliente_actualizado.direccion
    if "email" in cliente_actualizado.model_fields_set:
        if cliente.email != cliente_actualizado.email:
            campos_actualizados.append("email")
        cliente.email = cliente_actualizado.email
    if cliente_actualizado.usuario_id is not None:
        if cliente.usuario_id != cliente_actualizado.usuario_id:
            campos_actualizados.append("usuario_id")
        cliente.usuario_id = cliente_actualizado.usuario_id

    try:
        if campos_actualizados:
            registrar_auditoria(
                db=db,
                usuario=current_user,
                accion="ACTUALIZAR_CLIENTE",
                entidad="cliente",
                entidad_id=cliente.id,
                detalles={"campos_actualizados": campos_actualizados},
            )
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

    cliente_id = cliente.id
    db.delete(cliente)
    registrar_auditoria(
        db=db,
        usuario=current_user,
        accion="ELIMINAR_CLIENTE",
        entidad="cliente",
        entidad_id=cliente_id,
        detalles={"resultado": "ELIMINADO"},
    )
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

