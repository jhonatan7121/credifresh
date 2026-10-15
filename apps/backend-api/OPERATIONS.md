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

## Crear el primer administrador

El registro público solo crea usuarios `CLIENTE`. Para preparar una cuenta de
operación en una base que aún no tenga un administrador activo, desde
`apps/backend-api` ejecuta:

```powershell
python scripts/crear_admin.py
```

El comando solicita el correo y la contraseña de forma interactiva; la
contraseña no se muestra en pantalla. Exige al menos 12 caracteres y una
confirmación. Se niega a cambiar correos existentes o a crear otro
administrador cuando ya existe uno activo. No escribe credenciales ni hashes
en archivos. Guarda previamente un respaldo de la base y no ejecutes el
comando desde una terminal compartida.

Si se olvida esa contraseña, desde `apps/backend-api` se puede restablecer
únicamente la contraseña de una cuenta `ADMIN` activa existente:

```powershell
python scripts/restablecer_admin.py
```

El comando solicita el correo y la nueva contraseña de forma interactiva,
oculta la contraseña, exige confirmarla y no modifica el rol ni el estado de
la cuenta.

### Crear el primer administrador en Render Free

Render Free no ofrece una terminal para ejecutar `crear_admin.py`. Para una
base alojada vacía, despliega primero la versión de la API que incluye
`POST /auth/bootstrap-admin`. En el servicio API de Render, agrega
`ADMIN_BOOTSTRAP_TOKEN` con un secreto aleatorio de al menos 32 caracteres.
No lo compartas ni lo guardes en Git. En tu equipo, ejecuta:

```powershell
.\apps\backend-api\scripts\crear_admin_render.ps1
```

El script pregunta la URL HTTPS de la API, el correo, el token (oculto) y una
contraseña nueva (oculta; mínimo 12 caracteres). Envía esos datos directamente
a la API y no los escribe en archivos. El endpoint se mantiene cerrado si no
existe la variable, exige el token y rechaza el alta si ya existe cualquier
administrador activo. Al terminar correctamente, elimina
`ADMIN_BOOTSTRAP_TOKEN` de las variables del servicio Render. No vuelvas a
usar ese token. Después inicia sesión en el portal alojado y vincula la cuenta
de administración a los perfiles de clientes que correspondan.

Para generar un token hexadecimal aleatorio en Windows PowerShell o PowerShell 7:

```powershell
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
[BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
$rng.Dispose()
```

La respuesta no crea perfiles de clientes ni copia datos desde la base local;
esos registros se deben crear o vincular en la base alojada por separado.

## Operaciones bancarias

`BANK_OPERATIONS_ENABLED` permanece en `false` mientras no esté configurado el
proceso bancario. En ese estado, los endpoints de desembolso y registro de
pagos responden `503` y no cambian créditos, cuotas ni pagos. Esta variable no
conecta con un banco, no inicia transferencias ni confirma la recepción de
fondos: solo permite que la API registre esas operaciones internamente. No la
habilites hasta integrar y verificar el proceso de transferencia y conciliación.
Los tests usan una base SQLite aislada y activan la variable para ejercitar esos
flujos simulados. Cada intento administrativo bloqueado queda en
la auditoría con resultado `BLOQUEADO` y motivo, sin registrar el monto enviado.
Los inicios de sesión exitosos, fallidos y bloqueados, el registro público de
clientes, la creación de créditos y las operaciones de mantenimiento de clientes,
cuentas, usuarios y perfiles financieros también quedan auditados. La bitácora
guarda los nombres de los campos modificados, no cédulas, teléfonos, correos ni
cifras del perfil financiero; las contraseñas nunca se incluyen. Los eventos
financieros de aceptación, desembolso y pago conservan los importes necesarios
para su trazabilidad. Los eventos guardan la dirección del peer TCP observada
por la API; detrás de un proxy puede ser la dirección del proxy. La API no
confía en `X-Forwarded-For` sin una configuración explícita de proxies de
confianza.
Antes de desembolsar, la API vuelve a comparar monto, plazo, tasa, cuota y total
del plan con la aceptación registrada; cualquier diferencia bloquea la
operación y queda auditada.

## Docker

La migración es una operación de lanzamiento explícita, no una acción
automática al iniciar cada contenedor. Antes de desplegar una nueva versión,
ejecuta una sola vez:

```powershell
docker compose run --rm --no-deps backend-api alembic upgrade head
```

Después inicia la API normalmente. Esto evita carreras entre varias réplicas
de la aplicación.
