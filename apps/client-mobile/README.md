# CrediFresh para iPhone

App cliente nativa hecha con Expo y React Native. En el entorno local se conecta a la API de CrediFresh y al portal administrativo.

La configuración de Expo incluye el identificador iOS `com.credifresh.client`, el esquema de enlaces `credifresh` y el icono actualizado con la identidad navy, azul y verde de CrediFresh.

## Funciones disponibles

- Inicio de sesión y creación de cuenta de cliente. La contraseña debe tener mínimo 6 caracteres.
- Recuperación de contraseña por correo y cambio mediante enlace temporal de un solo uso. La contraseña nueva requiere mínimo 8 caracteres.
- Captura y edición de teléfono y dirección desde el perfil del cliente; quedan vinculados a sus solicitudes.
- Al crear cuenta, el equipo de CrediFresh debe verificar y vincular el perfil desde el portal antes de habilitar las solicitudes.
- Creación y actualización del perfil financiero, y solicitud de créditos entre $500.000 y $1.500.000 COP con plazo de 1 a 12 meses.
- Consulta de estados, condiciones y motivo de rechazo; aceptación explícita de una oferta aprobada.
- Bandeja de avisos del cliente, con actualización al volver a abrir la app y mientras está activa, contador de pendientes, opción de marcarlos leídos y acceso al crédito relacionado.
- Sincronización automática de créditos y avisos al volver a la app y cada minuto mientras está activa.
- Consulta de cuotas e historial de pagos, con saldo pendiente, vencimientos próximos y monto de cuotas vencidas cuando existan registros en la API.
- Sesión guardada de forma segura en iOS; una interrupción temporal del API conserva la sesión y permite reintentar, y un token vencido se elimina antes de volver al acceso.
- Comprobación manual de salud del API y visualización del servidor configurado para diagnosticar problemas de conexión desde el iPhone.

Aceptar una oferta no desembolsa el crédito. Los desembolsos y pagos reales siguen pendientes de la integración bancaria.

## Inicio local diario

1. Enciende Docker Desktop y verifica que el computador y el iPhone estén conectados a la misma red Wi-Fi.
2. Abre PowerShell y ejecuta:

   ```powershell
   cd "C:\Users\Usuario\Documents\GitHub\credifresh"
   .\start-credifresh-local.cmd
   ```

3. Mantén abierta la ventana. El comando inicia los servicios, reconstruye API y portal, aplica migraciones pendientes, actualiza la IP y prepara el enlace de recuperación para el puerto de Expo Go.
4. Escanea el QR con Expo Go.

Si Expo Go no detecta el servidor, revisa que ambos dispositivos sigan en la misma Wi-Fi. Si el servidor Expo se cerró, vuelve a ejecutar el comando.

## Configuración manual

Si no usas el iniciador de la raíz del proyecto, copia `.env.example` como `.env` y configura `EXPO_PUBLIC_API_BASE_URL` con la IP local del computador y el puerto `8000`, por ejemplo `http://192.168.1.25:8000`. No uses `localhost` en el iPhone: apuntaría al propio teléfono. Desde esta carpeta instala dependencias con `npm.cmd install` y ejecuta `npm.cmd start`.

## Antes de distribuirla a clientes

La versión actual está preparada para desarrollo y pruebas locales con Expo Go; todavía no es una publicación para clientes. Antes de distribuirla hacen falta una API desplegada con HTTPS y datos de producción, una revisión de privacidad y condiciones aplicables al manejo de datos financieros, y preparar la compilación/distribución de iOS. La integración bancaria seguirá siendo el paso final para habilitar desembolsos y pagos.
