"""Fail closed before migrations when explicitly seeding a disposable database."""
import os
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url


def main():
    if (os.getenv("ENVIRONMENT") != "sandbox" or os.getenv("WOMPI_ENVIRONMENT") != "sandbox"
            or os.getenv("WOMPI_SANDBOX_SEED_NEW_DISPOSABLE") != "true"
            or os.getenv("WOMPI_SANDBOX_SEED_DATA") != "true"):
        raise SystemExit("Explicit disposable Sandbox seed authorization required.")
    url = make_url(os.environ["DATABASE_URL"])
    name = (url.database or "").lower()
    if not url.drivername.startswith("postgresql") or not any(x in name for x in ("sandbox", "test")):
        raise SystemExit("Refusing to seed a database without a Sandbox/test name.")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        for schema in inspector.get_schema_names():
            if schema == "information_schema" or schema.startswith("pg_"):
                continue
            if inspector.get_table_names(schema=schema) or inspector.get_view_names(schema=schema):
                raise SystemExit("Refusing to seed an existing database containing tables or views.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
