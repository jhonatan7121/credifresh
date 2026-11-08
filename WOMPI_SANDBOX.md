# Prueba de recaudo Wompi Sandbox

La integración de recaudo de este backend es deliberadamente exclusiva de Sandbox. No acepta llaves `prv_prod_` ni secretos de recaudo `prod_events_`, y no envía solicitudes al API de producción.

## Configuración

En el entorno del backend configura, sin compartirlos por chat:

```text
WOMPI_ENVIRONMENT=sandbox
WOMPI_PRIVATE_KEY=prv_test_...
WOMPI_EVENTS_SECRET=test_events_...
```

Aplica las migraciones del backend con Alembic antes de probar. En Wompi configura la URL de eventos Sandbox como `https://<dominio-publico-del-api>/integraciones/wompi/sandbox/eventos`.

## Flujo

1. Con una cuenta cliente autenticada y un crédito de prueba desembolsado, llama `POST /integraciones/wompi/creditos/{credito_id}/cuotas/{cuota_id}/link`.
2. Abre `checkout_url` y completa el pago con los datos de prueba publicados por Wompi.
3. Wompi envía `transaction.updated`; el backend valida checksum, ambiente, link, monto y moneda antes de registrar el pago.
4. Consulta `GET /creditos/{credito_id}/pagos` y la amortización para verificar que el pago se aplicó una sola vez.

Los endpoints de link requieren usuario autenticado y solo permiten cobrar créditos desembolsados. Las llaves privadas y el secreto de eventos deben residir en variables de entorno del backend.

## Servicio de prueba aislado

El archivo `render.wompi-sandbox.yaml` define un servicio API, un portal de pruebas y un PostgreSQL dedicado al Sandbox. El plan y sus cargos se consultan en Render. No conectes este servicio a la base de producción ni uses datos reales. Las credenciales se ingresan solo en los campos secretos del servicio de pruebas.

La cuenta sintética se crea al inicio solo si `ENVIRONMENT=sandbox`, `WOMPI_ENVIRONMENT=sandbox` y `WOMPI_SANDBOX_SEED_DATA=true`. Su correo es `cliente.wompi.test@credifresh.invalid`; usa la contraseña cargada como secreto en el servicio. El crédito semilla es ficticio por COP 100.000 y no genera ningún desembolso real.

## Pagos a Terceros (pruebas aisladas)

El conector de Pagos a Terceros es independiente del flujo de recaudo. Solo funciona en el servicio aislado con `ENVIRONMENT=sandbox` y `WOMPI_PAYOUT_ENVIRONMENT=sandbox`; usa exclusivamente `https://api.sandbox.payouts.wompi.co/v1`.

En Render configura estas variables en `credifresh-wompi-sandbox`:

- `WOMPI_PAYOUT_API_KEY`
- `WOMPI_PAYOUT_USER_PRINCIPAL_ID`
- `WOMPI_PAYOUT_EVENTS_SECRET`
- `WOMPI_PAYOUT_ENVIRONMENT=sandbox`

No reutilices las credenciales de recaudo (`WOMPI_PRIVATE_KEY` y `WOMPI_EVENTS_SECRET`). No guardes secretos en el repositorio.

El secreto de eventos de Pagos a Terceros es independiente del de recaudo. Usa el secreto que muestra Wompi mientras el panel de Pagos a Terceros está en Sandbox; Wompi puede mostrarlo con prefijo `prod_events_`. La URL API y el `WOMPI_PAYOUT_ENVIRONMENT=sandbox` del servicio separado determinan que las solicitudes sigan en Sandbox.

La API de prueba requiere un usuario `ADMIN` autenticado y ofrece `GET /integraciones/wompi/payouts/sandbox/accounts`, `GET /integraciones/wompi/payouts/sandbox/banks`, `POST /integraciones/wompi/payouts/sandbox/lotes`, `GET /integraciones/wompi/payouts/sandbox/lotes?reference=...` para consultar directamente el lote en Wompi Sandbox, `GET /integraciones/wompi/payouts/sandbox/lotes/recientes` para inspeccionar referencias recientes sin datos bancarios, `GET /integraciones/wompi/payouts/sandbox/transactions/{reference}` para consultar una transacción por su referencia y el webhook `POST /integraciones/wompi/payouts/sandbox/eventos`.

La consulta de lotes y transacciones Sandbox debe verificarse por API (`GET /payouts?reference=...` y `GET /transactions/{reference}`). El panel de Wompi enfocado en historial de transacciones puede no mostrar operaciones de Sandbox; por eso la ausencia en ese panel no prueba por sí sola que el envío haya fallado.

El endpoint de lotes acepta solo una transacción sintética, estado explícito `APPROVED` o `FAILED` y monto máximo de $100.000 COP. `accountId` debe ser un ID de cuenta válido devuelto por el endpoint `accounts`; no uses valores de ejemplo como `WOMPI_ACCOUNT`. El servidor completa los datos del beneficiario con valores ficticios y no guarda ni devuelve datos bancarios reales. Tras desplegar esta versión, configura en Wompi Sandbox la URL HTTPS `https://credifresh-wompi-sandbox.onrender.com/integraciones/wompi/payouts/sandbox/eventos`. Esta URL es distinta del webhook de recaudo.

### Desembolso de un crédito ficticio

El portal Sandbox ofrece la sección **Prueba de desembolso Wompi**. El administrador selecciona un crédito aprobado con condiciones aceptadas, carga cuentas y bancos de prueba y elige resultado aprobado o rechazado. Los datos enviados al beneficiario son fijos y sintéticos; el monto proviene del crédito y está limitado a $1.500.000 COP.

También se puede usar `POST /integraciones/wompi/payouts/sandbox/creditos/{credito_id}/desembolso` con `accountId`, `bankId` y `transactionStatus` (`APPROVED` o `FAILED`). La API guarda una referencia única antes de llamar a Wompi y no vuelve a enviar automáticamente si el resultado es incierto. Para consultar el resultado confirmado se puede llamar `POST /integraciones/wompi/payouts/sandbox/creditos/{credito_id}/reconciliar`.

El webhook valida la firma y consulta la transacción directamente en Wompi. Solo cuando la referencia, el monto y el estado aprobado coinciden se registra el crédito como desembolsado y se generan las cuotas, en la misma transacción de base de datos. Un rechazo conserva el crédito pendiente. Si cambian las condiciones o no se puede aplicar el resultado, el intento queda en revisión manual. Los eventos repetidos no deben volver a generar cuotas.

Este flujo es exclusivo de Sandbox. No implementa datos de cuenta de clientes reales ni autoriza desembolsos en producción. Cada crédito admite un único intento Sandbox; un fallo o envío incierto requiere revisión antes de usar otro crédito de prueba.
