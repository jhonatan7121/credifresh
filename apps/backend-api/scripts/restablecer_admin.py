"""Interactively reset the password of an existing active ADMIN account.

Run from apps/backend-api with: python scripts/restablecer_admin.py
"""

from getpass import getpass
from pathlib import Path
import re
import sys

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIRECTORY))

from app.config.database import SessionLocal  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402


EMAIL_PATTERN = re.compile(r"^[\w.-]+@[\w.-]+\.\w+$")


def main() -> int:
    email = input("Correo de la cuenta ADMIN: ").strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        print("El correo no tiene un formato válido.")
        return 1

    password = getpass("Contraseña nueva (mínimo 12 caracteres): ")
    confirmation = getpass("Confirma la contraseña nueva: ")
    if len(password) < 12 or len(password.encode("utf-8")) > 72:
        print("La contraseña debe tener entre 12 y 72 bytes en UTF-8.")
        return 1
    if password != confirmation:
        print("Las contraseñas no coinciden.")
        return 1

    db = SessionLocal()
    try:
        usuario = (
            db.query(Usuario)
            .filter(
                Usuario.email == email,
                Usuario.rol == "ADMIN",
                Usuario.activo.is_(True),
            )
            .with_for_update()
            .first()
        )
        if usuario is None:
            print("No se encontró una cuenta ADMIN activa con ese correo; no hubo cambios.")
            db.rollback()
            return 1

        usuario.password_hash = get_password_hash(password)
        db.commit()
        print("Contraseña de la cuenta ADMIN restablecida correctamente.")
        return 0
    except Exception:
        db.rollback()
        print("No se pudo restablecer la contraseña. Revisa la conexión y el esquema de la base.")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
