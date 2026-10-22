# Prueba de recaudo Wompi Sandbox

La integración de este backend es deliberadamente exclusiva de Sandbox. No acepta llaves `prv_prod_` ni secretos `prod_events_`, y no envía solicitudes al API de producción.

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

El archivo `render.wompi-sandbox.yaml` define un servicio web gratuito separado. No crea ni enlaza una base PostgreSQL: usa SQLite bajo `/tmp`, cuyo contenido se descarta al reiniciar o recrear el contenedor. No agregues esta configuración a `render.yaml` ni la uses con datos reales. Las variables `WOMPI_PRIVATE_KEY`, `WOMPI_EVENTS_SECRET` y `WOMPI_SANDBOX_TEST_PASSWORD` deben ingresarse solo en los campos secretos del servicio de pruebas.

La cuenta sintética se crea al inicio solo si `ENVIRONMENT=sandbox`, `WOMPI_ENVIRONMENT=sandbox` y `WOMPI_SANDBOX_SEED_DATA=true`. Su correo es `cliente.wompi.test@credifresh.invalid`; usa la contraseña cargada como secreto en el servicio. El crédito semilla es ficticio por COP 100.000 y no genera ningún desembolso real.
