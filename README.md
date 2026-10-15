# CrediFresh

CrediFresh es una aplicación local para administrar clientes y solicitudes de crédito. Incluye una API FastAPI, PostgreSQL y un portal web administrativo que también presenta la vista del cliente según su rol.

## Funciones disponibles

- Inicio de sesión y registro público de cuentas de cliente.
- Recuperación de contraseña por enlace de correo temporal y de un solo uso; requiere un proveedor SMTP configurado.
- Registro y edición del teléfono y dirección del cliente, compartidos por su perfil con las solicitudes de crédito.
- Administración de usuarios, clientes y perfiles financieros.
- Creación y evaluación de solicitudes mediante las reglas configuradas en el proyecto.
- Consulta del resultado, simulación del plan de amortización y aceptación de condiciones desde la sesión vinculada del cliente.
- Panel de cartera, auditoría administrativa, notificaciones e historial de pagos.

Una solicitud aprobada y aceptada no significa que el dinero haya sido transferido. La integración con bancos o proveedores de pago todavía no está configurada. Los desembolsos y pagos permanecen bloqueados de forma predeterminada; no cambies `BANK_OPERATIONS_ENABLED` para simular una transferencia real.

## Ejecutar localmente con Docker Compose

Usa Docker Desktop y ejecuta estos pasos desde la raíz del repositorio. Configura un archivo `.env` en esa carpeta con una clave secreta para `SECRET_KEY`. Si vas a usar una base PostgreSQL distinta de la predeterminada, define también `CREDIFRESH_DATABASE_URL` con la dirección de esa base. No compartas ni subas el `.env` al repositorio.

Para habilitar la recuperación de contraseñas, agrega al `.env` los datos suministrados por tu proveedor SMTP; guarda `SMTP_PASSWORD` como secreto:

```dotenv
SMTP_HOST=smtp.tu-proveedor.com
SMTP_PORT=587
SMTP_USE_SSL=false
SMTP_USERNAME=cuenta-de-envio
SMTP_PASSWORD=secreto-del-proveedor
SMTP_FROM_EMAIL=soporte@tu-dominio.com
RESET_PASSWORD_URL=credifresh://reset-password
```

El iniciador local configura `RESET_PASSWORD_URL` para abrir una página web de recuperación en el portal local (`http://IP-DEL-COMPUTADOR:3000/reset-password.html`). Esa página envía la nueva contraseña al API y funciona desde el navegador del teléfono mientras el computador y el teléfono estén en la misma red. Para un despliegue, usa una URL HTTPS bajo el dominio público de la app y configura los orígenes CORS correspondientes.

```powershell
docker compose config -q
docker compose up -d postgres
docker compose run --rm --no-deps backend-api alembic upgrade head
docker compose up -d --build
```

Antes de aplicar migraciones, confirma que `CREDIFRESH_DATABASE_URL` apunta a la base prevista. Las migraciones cambian su esquema. No borres ni reinicies bases que ya contengan datos.

- Portal: `http://localhost:3000`
- API: `http://localhost:8000`
- Documentación interactiva: `http://localhost:8000/docs`
- Verificación de salud de API y base de datos: `http://localhost:8000/health`

Para crear el primer administrador, consulta [`apps/backend-api/OPERATIONS.md`](apps/backend-api/OPERATIONS.md). El portal obtiene la dirección pública de la API desde `API_BASE_URL`; la API solo acepta los orígenes listados en `ALLOWED_ORIGINS`.

## API

Los routers principales están disponibles en la documentación interactiva:

- `/auth`: registro, inicio de sesión y sesión actual.
- `/usuarios`: consulta y administración de cuentas.
- `/clientes`: clientes, vinculación de cuentas y perfiles financieros.
- `/creditos`: solicitudes, evaluación, aceptación, simulación de amortización, desembolso y pagos.
- `/reportes`, `/auditoria`, `/notificaciones` y `/simulador`.

Las rutas protegidas requieren autenticación y aplican permisos según el rol. El código fuente de cada router documenta sus campos y respuestas.

## Ejecutar pruebas del backend

Desde `apps/backend-api`, instala `requirements-dev.txt`. Para ejecutar solo las pruebas que usan la base SQLite en memoria, configura variables temporales en PowerShell y excluye las pruebas que requieren PostgreSQL:

```powershell
$env:DATABASE_URL = "sqlite:///:memory:"
$env:SECRET_KEY = "clave-temporal-solo-para-pruebas"
python -m pytest -q --ignore=tests/test_postgres_integration.py --ignore=tests/test_concurrency.py
Remove-Item Env:DATABASE_URL, Env:SECRET_KEY
```

`conftest.py` activa operaciones bancarias únicamente dentro de la suite aislada; eso no habilita transferencias desde la aplicación local.

Para las pruebas PostgreSQL y de concurrencia, usa un contenedor temporal sin volumen persistente. Estos tests limpian las tablas de la base `credifresh_test_db`:

```powershell
# Desde la raíz del repositorio
docker run --rm -d --name credifresh-postgres-isolated-tests -p 127.0.0.1:5434:5432 -e POSTGRES_USER=test_user -e POSTGRES_PASSWORD=credifresh_local_test_only -e POSTGRES_DB=postgres postgres:15-alpine
docker exec credifresh-postgres-isolated-tests pg_isready -U test_user -d postgres
```

Cuando PostgreSQL acepte conexiones, desde `apps/backend-api` define las variables y ejecuta primero integración para crear la base y aplicar migraciones, y luego concurrencia:

```powershell
$env:POSTGRES_TEST_DATABASE_URL = "postgresql+psycopg://test_user:credifresh_local_test_only@127.0.0.1:5434/credifresh_test_db"
$env:DATABASE_URL = $env:POSTGRES_TEST_DATABASE_URL
$env:SECRET_KEY = "clave-temporal-solo-para-pruebas"
python -m pytest -q tests/test_postgres_integration.py
python -m pytest -q tests/test_concurrency.py
Remove-Item Env:POSTGRES_TEST_DATABASE_URL, Env:DATABASE_URL, Env:SECRET_KEY
```

Detén el contenedor temporal al terminar; al no tener volumen, sus datos de prueba se eliminan con él:

```powershell
docker stop credifresh-postgres-isolated-tests
```

## Estado de publicación

El archivo [`render.yaml`](render.yaml) prepara una prueba gratuita en Render con la API, un portal estático y PostgreSQL. Selecciona planes gratuitos y deja desactivados los despliegues automáticos. El portal genera `config.js` durante la compilación para conectarse a la API.

Este entorno es temporal y solo sirve para probar: Render puede dormir la API después de 15 minutos sin tráfico, por lo que la primera petición puede tardar cerca de un minuto. PostgreSQL gratuito tiene 1 GB, no incluye copias de seguridad y vence a los 30 días; si vence, los datos se eliminan después del periodo de gracia del proveedor. No uses información real de clientes. Render Free bloquea el envío SMTP saliente en los puertos habituales, así que el restablecimiento de contraseña por correo no funcionará con la configuración SMTP actual.

El despliegue usa una base nueva y vacía. Antes de distribuir una app iOS, configura `EXPO_PUBLIC_API_BASE_URL` con la URL HTTPS de la API y compila una versión de producción. Para operar con datos reales, disponibilidad continua, respaldo y correo, habrá que planear un entorno de pago y revisar sus costos. La transferencia bancaria y la conciliación de fondos siguen siendo un paso posterior.
