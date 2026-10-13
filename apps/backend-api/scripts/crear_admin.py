"""Create the first active CrediFresh administrator interactively.

Run from apps/backend-api with: python scripts/crear_admin.py
"""

from getpass import getpass
from pathlib import Path
import re
import sys

from sqlalchemy import text

# Allow running this file directly while keeping application imports intact.
BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIRECTORY))

from app.config.database import SessionLocal  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402


EMAIL_PATTERN = re.compile(r"^[\w.-]+@[\w.-]+\.\w+$")


def main() -> int:
    email = input("Correo del nuevo administrador: ").strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        print("El correo no tiene un formato válido.")
        return 1

    password = getpass("Contraseña nueva (mínimo 12 caracteres): ")
    confirmation = getpass("Confirma la contraseña: ")
    if len(password) < 12:
        print("La contraseña debe tener al menos 12 caracteres.")
        return 1
    if password != confirmation:
        print("Las contraseñas no coinciden.")
        return 1

    db = SessionLocal()
    try:
        # Serialize bootstrap attempts in PostgreSQL so only one first admin
        # can be created when two operators run the command at once.
        if db.bind.dialect.name == "postgresql":
            db.execute(text("LOCK TABLE usuarios IN EXCLUSIVE MODE"))

        active_admin = (
            db.query(Usuario)
            .filter(Usuario.rol == "ADMIN", Usuario.activo.is_(True))
            .first()
        )
        if active_admin:
            print("Ya existe un administrador activo; no se realizaron cambios.")
            db.rollback()
            return 1

        existing_user = db.query(Usuario).filter(Usuario.email == email).first()
        if existing_user:
            print("Ese correo ya está registrado; no se modificó ninguna cuenta.")
            db.rollback()
            return 1

        db.add(
            Usuario(
                email=email,
                password_hash=get_password_hash(password),
                rol="ADMIN",
                activo=True,
            )
        )
        db.commit()
        print("Administrador creado correctamente.")
        return 0
    except Exception:
        db.rollback()
        print("No se pudo crear el administrador. Revisa la conexión y el esquema de la base.")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
