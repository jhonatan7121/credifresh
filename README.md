# CrediFresh

Backend inicial para gestionar clientes y solicitudes de crédito.

## Ejecutar localmente

1. Entra al directorio del backend:

   ```powershell
   cd apps/backend-api
   ```

2. Crea un archivo `.env` a partir de `.env.example` y asigna la URL de PostgreSQL:

   ```env
   DATABASE_URL=postgresql+psycopg2://usuario:contrasena@localhost:5432/credifresh
   ```

3. Activa el entorno virtual e instala dependencias:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. Inicia la API:

   ```powershell
   uvicorn main:app --reload
   ```

La documentación interactiva queda disponible en `http://127.0.0.1:8000/docs`.

## Endpoints principales

- `GET /clientes/` y `GET /clientes/{id}`
- `POST /clientes/`, `PUT /clientes/{cedula}` y `DELETE /clientes/{cedula}`
- `GET /creditos/`, con filtro opcional `?cliente_id={id}`
- `GET /creditos/{id}` y `POST /creditos/`
- `PATCH /creditos/{id}/estado`

Los estados permitidos para un crédito son `SOLICITADO`, `APROBADO` y `RECHAZADO`.

## Docker

Desde `apps/backend-api`, crea la imagen y ejecútala proporcionando la URL de base de datos:

```powershell
docker build -t credifresh-api .
docker run --env-file .env -p 8000:8000 credifresh-api
```
