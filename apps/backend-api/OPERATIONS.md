# Operación de CrediFresh

## Desarrollo local

Guarda `DATABASE_URL` y `SECRET_KEY` fuera de Git, en `.env`. Para instalar
las dependencias de desarrollo y ejecutar las validaciones:

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p test_migrations.py -v
python -m pytest -q
```

## Aplicar migraciones

En una base vacía, antes de iniciar la API:

```powershell
python -m alembic upgrade head
```

Para una base que ya contiene datos, primero realiza un respaldo y compara
el esquema con los modelos. Solo si coincide con la migración inicial, marca
la versión sin modificar los datos:

```powershell
python -m alembic stamp head
```

No se deben ejecutar downgrades de la migración inicial: están bloqueados
porque eliminarían tablas y datos.

## Docker

La migración es una operación de lanzamiento explícita, no una acción
automática al iniciar cada contenedor. Antes de desplegar una nueva versión,
ejecuta una sola vez:

```powershell
docker run --rm --env-file .env credifresh-api python -m alembic upgrade head
```

Después inicia la API normalmente. Esto evita carreras entre varias réplicas
de la aplicación.
