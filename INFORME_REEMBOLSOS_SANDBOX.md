# Política de reembolsos Sandbox: informe técnico para revisión

## Estado

Implementación parcial, **no lista para despliegue**. La solicitud y la aprobación administrativa están implementadas; la ejecución nueva se bloquea deliberadamente. No se modifica el servicio de producción ni se efectúan operaciones ante Wompi en este trabajo. Los datos y credenciales empleados en las pruebas son sintéticos.

## Conflicto que impide cerrar la implementación

La ruta existente `POST /integraciones/wompi/sandbox/creditos/{credito_id}/cuotas/{cuota_id}/reembolso` permite enviar un reembolso sin una solicitud previamente aprobada. Su reserva atómica y sus controles actuales evitan duplicar envíos, pero no exigen la nueva autorización. Por instrucciones de preservar el comportamiento anterior cuando hay un conflicto, se conservó la ruta existente. **Por tanto, activar el nuevo indicador no garantiza que todas las solicitudes a Wompi se autoricen previamente.**

Riesgo: una persona con rol ADMIN podría omitir el flujo nuevo invocando la ruta anterior directamente. El indicador nuevo no protege la ruta anterior. No se debe desplegar ni presentar esta política como aplicada mientras persista este conflicto. Para resolverlo de forma segura se propone añadir una comprobación obligatoria y transaccional de la solicitud aprobada a la ruta anterior o retirarla en una migración de API controlada, preservando las consultas y registros históricos, y adaptar a ese cambio los clientes y las pruebas existentes. Esto requiere revisar expresamente la modificación del contrato anterior. No se intenta esquivar el conflicto mediante otro endpoint.

## Trabajo realizado

- Modelo independiente `solicitudes_reembolso_sandbox`, vinculado al pago y a crédito y cuota, con campos de autorización, clasificación y futura conciliación. Mantiene una sola solicitud por pago; no migra ni altera `wompi_reembolsos_sandbox`.
- Migración Alembic `f16c47d390a1` con reversión protegida cuando hay solicitudes registradas. No convierte ni reclasifica el reembolso histórico 32935.
- Indicador `WOMPI_SANDBOX_REFUND_POLICY_ENABLED`, apagado por defecto. Las nuevas rutas requieren runtime Sandbox, Wompi Sandbox, llave con prefijo de prueba y usuario ADMIN.
- El registro verifica el pago interno y consulta la transacción original mediante el servicio existente de Wompi: ID, aprobación, link, moneda y monto. Las categorías de motivo y clasificación son independientes; OTRO exige descripción ampliada.
- Una decisión aprobada conserva una huella de los datos materiales. Aprobar no llama al endpoint de Wompi. La revisión de clasificación se audita y no crea asientos. No existe edición de datos materiales por API.
- Se añadió un panel inicial visible únicamente cuando el servicio nuevo está habilitado; ofrece registro, listado y decisión, y advierte que la ejecución y conciliación están bloqueadas. Es un prototipo incompleto para revisión, no el panel final.
- La ruta de ejecución nueva devuelve HTTP 409 incluso para una solicitud aprobada y no realiza una operación externa. No se alteran pagos, cuotas, intereses o amortizaciones.

## Rutas nuevas

Todas bajo `/integraciones/wompi/sandbox/solicitudes-reembolso`: `POST` registrar, `GET` listar, `GET /{id}` detalle y auditoría, `POST /{id}/decision`, `POST /{id}/revision-contable`, `POST /{id}/ejecutar` (siempre bloqueada). Las rutas históricas no se modificaron.

## Verificación local

- Suite local de regresión: **229 aprobadas y 7 omitidas** (pruebas PostgreSQL no configuradas en esa ejecución; se excluyeron `test_concurrency.py` y `test_postgres_integration.py`).
- Con PostgreSQL 15 aislado y datos ficticios: **7 aprobadas**, incluidas las pruebas de concurrencia Wompi existentes y dos solicitudes simultáneas de la nueva política; se creó una sola solicitud y no se alteró la cuota. Se eliminó el contenedor temporal al terminar.
- `node --check apps/admin-portal/app.js`: correcto.
- Estas verificaciones no demuestran el flujo completo ni su seguridad en producción. No se enviaron solicitudes de reembolso a Wompi ni se comprobó información bancaria real.

## Pendiente antes de considerar cumplidos los criterios

1. Resolver la incompatibilidad de la ruta anterior; demostrar que ninguna ruta puede enviar sin aprobación, incluida la concurrencia y las condiciones de error.
2. Implementar la ejecución explícita con reserva persistente, estado incierto y verificación sin reenvíos, y relacionarla con la aprobación congelada.
3. Implementar verificación independiente del proveedor y conciliación operativa sintética, la gestión de diferencias y el cierre contable; no se deben presentar como conciliación bancaria real.
4. Completar el panel: filtros por fecha, detalle, historial, revisión contable, consulta de proveedor y reporte seguro. La distribución entre capital e intereses no se afirma como verificable porque el pago actual no la desglosa.
5. Ejecutar pruebas del flujo completo, fallos y timeouts, concurrencia del envío, eventos y saldos antes/después, migración y regresión, sin tocar el histórico.
6. Revisar con el responsable contable las clasificaciones antes de cualquier eventual uso real.

El endpoint `GET /v1/refunds/{id}` se ha observado en pruebas anteriores, pero la guía pública de Wompi consultada documenta el POST V2 y no acredita aquí ese GET como contrato general: no se debe basar el diseño final en esa ruta sin confirmación adicional. Fuente: https://docs.wompi.co/docs/colombia/reembolsos-sandbox/.
