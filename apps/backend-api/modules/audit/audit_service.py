import json
from app.models.audit_log import AuditLog
from app.models.usuario import Usuario


def registrar_auditoria(
    db,
    usuario: Usuario | None,
    accion: str,
    entidad: str,
    entidad_id: int | None,
    resultado: str = "EXITOSO",
    detalles: dict | str | None = None,
    ip: str | None = None
):
    """
    Registra un evento de auditoría en la sesión de base de datos actual.
    No realiza commit independiente para garantizar atomicidad transaccional.
    """
    usuario_id = usuario.id if usuario else None
    rol = usuario.rol if usuario else "SISTEMA"

    detalles_str = None
    if isinstance(detalles, dict):
        # Sanitizar preventivamente por si se pasan claves prohibidas
        sanitized = {
            k: v for k, v in detalles.items()
            if not any(secret in k.lower() for secret in ["password", "token", "secret", "key", "hash"])
        }
        detalles_str = json.dumps(sanitized, ensure_ascii=False)
    elif isinstance(detalles, str):
        detalles_str = detalles

    audit_entry = AuditLog(
        usuario_id=usuario_id,
        rol=rol,
        accion=accion,
        entidad=entidad,
        entidad_id=entidad_id,
        resultado=resultado,
        detalles=detalles_str,
        ip=ip
    )
    db.add(audit_entry)
