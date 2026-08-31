import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.api.v1.endpoints.clientes import router as clientes_router
from app.api.v1.endpoints.creditos import router as creditos_router
from app.api.v1.endpoints.perfil_financiero import router as perfil_financiero_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.reportes import router as reportes_router
from app.api.v1.endpoints.auditoria import router as auditoria_router
from app.api.v1.endpoints.notificaciones import router as notificaciones_router

from app.api.v1.endpoints.simulador import router as simulador_router


from app.config.database import engine

app = FastAPI(
    title="CrediFresh API",
    version="1.0.0",
    description="Backend oficial de CrediFresh"
)

allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [
    origin.strip()
    for origin in allowed_origins_env.split(",")
    if origin.strip()
]

if os.getenv("ENVIRONMENT") == "production" and "*" in allowed_origins:
    raise RuntimeError("No se permite utilizar wildcard (*) en ALLOWED_ORIGINS en entorno de producción.")


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clientes_router)
app.include_router(creditos_router)
app.include_router(perfil_financiero_router)
app.include_router(auth_router)
app.include_router(reportes_router)
app.include_router(simulador_router)

app.include_router(notificaciones_router)

app.include_router(auditoria_router)

@app.get("/")
def home():
    return {
        "application": "CrediFresh",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Base de datos no disponible"
        )

    return {
        "status": "healthy"
    }
