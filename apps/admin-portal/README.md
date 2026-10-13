# Portal web CrediFresh

El portal se sirve como sitio estático con Nginx. La dirección de la API se inyecta cuando inicia el contenedor, así puedes usar la misma imagen en desarrollo y en el servidor.

## Desarrollo local con Docker Compose

Los valores predeterminados apuntan al portal en `http://localhost:3000` y a la API en `http://localhost:8000`. Para cambiarlos, define estas variables en el archivo `.env` de la raíz del proyecto:

```dotenv
API_BASE_URL=http://localhost:8000
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
ENVIRONMENT=development
```

`API_BASE_URL` debe ser una dirección accesible desde el navegador de cada usuario, no el nombre interno del servicio Docker.

## Probar sin usar las bases existentes

No uses `credifresh_test_db` para pruebas nuevas: ya contiene registros. Crea una base independiente, por ejemplo `credifresh_portal_test_db`, y configura `CREDIFRESH_DATABASE_URL` en el `.env` de la raíz para que solo la API local use esa base:

```dotenv
CREDIFRESH_DATABASE_URL=postgresql+psycopg://credifresh_user:credifresh_password@postgres:5432/credifresh_portal_test_db
```

La conexión predeterminada sigue usando `credifresh_db` mientras no definas esa variable. Antes de iniciar el backend con la conexión de prueba, confirma que la base nueva está vacía y aplica las migraciones solo allí. No borres ni reinicies `credifresh_db` o `credifresh_test_db`.

## Configuración para publicar

Antes de publicar, configura en `.env`:

```dotenv
API_BASE_URL=https://api.tu-dominio.com
ALLOWED_ORIGINS=https://tu-dominio.com
ENVIRONMENT=production
```

Reemplaza ambos dominios por los dominios HTTPS reales. Si también sirves el portal en `www` u otro dominio, agrega cada origen exacto separado por comas. No uses `*` en producción. La API valida y rechaza esa configuración.

El servicio `admin-portal` genera `/config.js` desde `config.template.js` al iniciar Nginx. Después de cambiar las variables, recrea los contenedores correspondientes para aplicar la configuración. Mantén `SECRET_KEY` fuera del repositorio y usa un valor secreto distinto del de desarrollo; las operaciones bancarias permanecen desactivadas por defecto hasta que se habiliten deliberadamente.

Esta configuración prepara el portal para despliegue; no aprovisiona dominios, certificados TLS, base de datos de producción ni credenciales de usuario.
