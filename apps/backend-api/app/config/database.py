import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Support the original app-local .env file and the project-root .env used by
# the current repository layout. Existing process environment values win.
app_directory = Path(__file__).resolve().parents[1]
backend_directory = Path(__file__).resolve().parents[2]
project_directory = Path(__file__).resolve().parents[4]
load_dotenv(app_directory / ".env")
load_dotenv(backend_directory / ".env")
load_dotenv(project_directory / ".env")


DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está configurada")

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
