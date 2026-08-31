from sqlalchemy.orm import Session
from app.models.notificacion import Notificacion


def crear_notificacion(
    db: Session,
    usuario_id: int,
    titulo: str,
    mensaje: str,
    credito_id: int | None = None
) -> Notificacion:
    """Crea una notificación sin ejecutar commit independiente.

    La transacción se gestiona de forma atómica en el flujo principal.
    """
    notificacion = Notificacion(
        usuario_id=usuario_id,
        titulo=titulo,
        mensaje=mensaje,
        credito_id=credito_id,
        leida=False
    )
    db.add(notificacion)
    db.flush()
    return notificacion
