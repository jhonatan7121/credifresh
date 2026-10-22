import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Support the original app-local .env file and the project-root .env used by
# the current repository layout. Existing process environment values win.
app_directory = Path(__file__).resolve().parents[1]
backend_directory = Path(__file__).resolve().parents[2]
project_directory = Path(__file__).resolve().parents[3]
load_dotenv(app_directory / ".env")
load_dotenv(backend_directory / ".env")
load_dotenv(project_directory / ".env")


DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está configurada")

SIMULATION_MODE = os.getenv("SIMULATION_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
if SIMULATION_MODE:
    from urllib.parse import unquote, urlparse

    parsed_database_url = urlparse(DATABASE_URL)
    raw_database_path = unquote(parsed_database_url.path)
    if len(raw_database_path) >= 3 and raw_database_path[0] == "/" and raw_database_path[2] == ":":
        raw_database_path = raw_database_path[1:]
    database_path = Path(raw_database_path).resolve()
    repository_root = Path(__file__).resolve().parents[4]
    simulation_root = repository_root / ".simulation"
    if parsed_database_url.scheme != "sqlite" or database_path.parent != simulation_root.resolve() or database_path.name != "credifresh_simulation.db":
        raise RuntimeError("SIMULATION_MODE solo permite .simulation/credifresh_simulation.db local.")

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
