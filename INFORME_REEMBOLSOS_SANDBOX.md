# Política de reembolsos Sandbox: informe técnico para revisión

## Validación local más reciente

Tres escenarios usaron el backend Uvicorn real, PostgreSQL local aislado y el simulador HTTP en loopback. El backend se terminó y reinició antes del envío de reembolso y después de la recepción por el simulador; en ambos se recuperó INCIERTO y se bloqueó el reintento con 409. Un tercer escenario terminó la conexión de coordinación PostgreSQL durante la espera HTTP y recuperó la reserva antes de la respuesta: la respuesta tardía devolvió 409, no sobrescribió INCIERTO y solo hubo un POST simulado. Antes del POST hubo cero envíos y después de la recepción hubo uno. Las tres cuotas ficticias conservaron estado PAGADA y valor 1250,00. La antigüedad se simuló ajustando únicamente la fecha de reserva en la base temporal. Evidencia: `C:\Users\Usuario\Documents\Codex\credifresh-refund-browser-test\evidencia-interrupciones.json` y `interrupciones_http.py`.

Se corrigió la pérdida de conexión durante la liberación del bloqueo para no ocultar el conflicto original. La regresión posterior pasó 250 pruebas y la suite separada de integración PostgreSQL pasó 10. Las pruebas de navegador anteriores verificaron creación, aprobación, reembolso simulado, consulta, cotejo, revisión contable, auditoría, rechazo, visualización de INCIERTO y bloqueo de GESTOR. No se completó una matriz exhaustiva de todos los errores, roles y estados en navegador. La consulta por ID de reembolso sigue dependiendo de un contrato observado en Sandbox que requiere confirmación documental de Wompi. No se tocó producción ni se consultó o modificó el histórico real 32935. Recomendación: revisión técnica y de seguridad antes de cualquier autorización de despliegue.

## Validación HTTP y navegador local adicional

La API Uvicorn, PostgreSQL y un servidor HTTP ficticio se ejecutaron en loopback con credenciales sintéticas. La evidencia reproducible está en `C:\Users\Usuario\Documents\Codex\credifresh-refund-browser-test` (`interrupciones_http.py`, `evidencia-interrupciones.json`, `panel-inciertos.png`, `panel-gestor.png`).

| Escenario | Resultado | Evidencia |
| --- | --- | --- |
| Interrupción del backend tras reservar y antes del POST de reembolso | APROBADO | Simulador bloqueó la consulta previa; proceso terminado y reiniciado; 0 POST, INCIERTO, reintento 409. |
| Interrupción esperando respuesta después de recepción del POST | APROBADO | Simulador registró 1 POST y retuvo respuesta; backend terminado y reiniciado; INCIERTO, reintento 409. |
| Cuotas y auditoría | APROBADO | Tres cuotas sintéticas PAGADAS por 1250,00; para cada reserva hay auditoría de creación y recuperación. |
| Estados inciertos en panel y acceso de GESTOR | APROBADO | Playwright observó dos INCIERTO y el panel rechazó acceso GESTOR. |
| Respuesta tardía en proceso real e interrupción antes de recepción de bytes del POST | NO EJECUTADO | El backend se terminó después de la recepción del POST, por lo que su proceso ya no puede procesar una respuesta tardía; falta escenario específico. |
| Panel: errores y todos los roles, ejecución rechazada e incierta | PARCIAL | Hay pruebas en navegador de ADMIN, GESTOR, aprobación, rechazo, ejecución, cotejo, auditoría y revisión contable; no cubren todos los casos solicitados. |

No se desplegó ni se usaron datos reales. El reloj de la reserva sintética se adelantó en la base temporal para superar el umbral; no se alteraron cuotas. La base se eliminó tras la prueba. No se recomienda desplegar hasta completar los casos pendientes y efectuar revisión de seguridad.

**Navegador integrado local:** Playwright con Edge accedió al panel servido localmente y a la API local conectada a PostgreSQL temporal. Con datos sintéticos se verificó creación, aprobación y ejecución de una solicitud, consulta del proveedor simulado, cotejo, revisión contable y auditoría visible; otra solicitud fue rechazada y permaneció sin envío. El simulador registró una solicitud de reembolso; las dos cuotas de prueba permanecieron PAGADAS por 1250,00. Evidencias y scripts están en `C:\Users\Usuario\Documents\Codex\credifresh-refund-browser-test`. Una primera automatización agotó el tiempo de espera al buscar el mensaje de éxito aunque la solicitud quedó creada; una segunda confirmó y completó la operación, y un tercer recorrido confirmó el rechazo. Esto no demuestra cobertura integral de la interfaz.

**Pendiente bloqueante:** no se ejecutaron los reinicios reales del backend con interrupción HTTP en A/B/C, ni todas las validaciones de interfaz de roles, errores y estados inciertos. El simulador y lanzador aún requieren orquestación controlada para detener y reiniciar el servidor y contar solicitudes. No se modificaron servicios remotos ni se desplegó; no se recomienda despliegue.

**Preparación local posterior:** se amplió el simulador HTTP de loopback para recibir solicitudes ficticias y registrar referencias, y se preparó un lanzador separado que exige PostgreSQL local aislado, llave sintética y bloquea destinos externos mediante `urllib`. Se verificó `/health` y que el lanzador rechace una URL SQLite. No se han integrado todavía backend, panel, datos y simulador ni ejecutado las pruebas funcionales o interrupciones HTTP; estas siguen NO EJECUTADAS. El lanzador no es una barrera de red general: controla únicamente llamadas mediante `urllib.request.urlopen`. No desplegar.

**Revisión de herramientas:** Playwright está instalado fuera del repositorio y Edge pudo abrir el panel local; la captura inicial de acceso existe. Se preparó un esqueleto de servidor local que responde en `/health` pero devuelve 501 en `/v1/refunds`; no constituye un simulador funcional. La API de CrediFresh fija la URL Sandbox de Wompi en código, por lo que falta un lanzador de pruebas que redirija de forma segura exclusivamente al loopback y prepare datos sintéticos. No se realizaron las pruebas integradas de navegador o interrupción HTTP. No desplegar.

**Comprobación de herramientas de navegador:** Playwright se instaló fuera del repositorio en `C:\Users\Usuario\Documents\Codex\credifresh-refund-browser-test`; Edge sin interfaz abrió el HTML local y mostró el formulario de acceso. Se guardaron `smoke-panel.cjs` y `panel-acceso.png`. Esta es únicamente una comprobación inicial sin backend; no valida inicio de sesión ni el flujo de reembolsos. Los escenarios HTTP de reinicio y el recorrido integrado permanecen NO EJECUTADOS: aún falta implementar y aislar un simulador HTTP y un lanzador del backend local con configuración sintética. No habilitar ni desplegar.

## Estado de cierre local solicitado

| Escenario | Estado | Evidencia o límite |
| --- | --- | --- |
| Panel administrativo completo en navegador con backend local | NO EJECUTADO | Edge está instalado; no se preparó el entorno automatizado con el proveedor simulado. |
| A: detener backend web antes del HTTP | NO EJECUTADO | Existe terminación de trabajador Python, no del servidor web. |
| B: detener backend durante HTTP | NO EJECUTADO | No se montó servidor HTTP simulado. |
| C: proveedor recibe y backend cae antes de guardar | NO EJECUTADO | Las pruebas actuales simulan funciones internas, no recepción HTTP independiente. |
| D: reinicio real del servidor web | NO EJECUTADO | Las pruebas abren una nueva sesión tras terminar un trabajador, no reinician Uvicorn. |
| E: recuperación coordinada | APROBADO PARCIAL | Probada en PostgreSQL con reserva sintética antigua y procesos concurrentes; falta repetir tras reinicio real del servidor. |
| F: bloqueo de reenvío | APROBADO PARCIAL | Probado tras timeout e interrupción de trabajador; no tras interrupción HTTP real del servidor. |
| G: respuesta tardía o contradictoria | APROBADO PARCIAL | Probada mediante funciones simuladas, sin comunicación HTTP real. |
| H: contar solicitudes en servidor HTTP simulado | NO EJECUTADO | No se montó el servidor simulado. |
| Rutas antigua y nueva sin aprobación o con indicador ausente | APROBADO | Prueba focalizada `test_ambas_rutas_exigen_aprobacion_y_flag`; no realiza llamadas de reembolso. |

Última regresión: 249 pruebas aprobadas con PostgreSQL aislado, ejecutada antes de agregar la prueba focalizada de ambas rutas; esta prueba adicional pasó por separado. Suite de integración y concurrencia general PostgreSQL: 10 aprobadas. No se verificó la base remota ni se modificó el registro histórico 32935. Recomendación: **no autorizar despliegue** mientras el panel y los escenarios HTTP y de reinicio sigan sin ejecutarse.

**Pruebas locales adicionales:** tres trabajadores Python fueron terminados intencionalmente con `os._exit` después de persistir la reserva; una sesión nueva recuperó cada una como INCIERTO y bloqueó un nuevo envío. El proveedor es una función simulada dentro del trabajador; las etiquetas durante/después no prueban una comunicación HTTP real ni el reinicio del servidor web. La regresión local pasó 249 pruebas y la suite general restante sobre PostgreSQL aislado pasó 10. No se efectuó la prueba funcional del panel en navegador ni se comprobó un reinicio real del backend web. No está listo para desplegar.

**Validación adicional de interrupciones:** se simularon interrupciones mediante excepciones antes y durante la comunicación y se abrió una sesión nueva para comprobar que la reserva persiste y que se bloquea el reenvío. Las 20 pruebas focalizadas pasaron. Estas pruebas no equivalen a terminar y reiniciar un proceso real ni comprueban aún el panel en navegador; siguen pendientes antes del despliegue.

**Validación adicional:** se agregaron alertas auditables cuando la consulta autenticada arroja estado, monto o transacción incompatibles; las pruebas simulan confirmación seguida de contradicción y una respuesta tardía tras marcar una operación incierta. La regresión local con PostgreSQL aislado ejecutó 244 pruebas sin fallos; las pruebas generales restantes de PostgreSQL se ejecutaron por separado: 10 aprobadas. No se probó funcionalmente el panel en navegador ni se simularon todos los reinicios e interrupciones solicitados. Las pruebas de respuesta tardía no sustituyen una caída real del proceso. No está listo para despliegue; mantener apagado el indicador.

**Coordinación y recuperación, avance local:** se usa un bloqueo asesor de sesión PostgreSQL durante la ejecución y un bloqueo asesor transaccional breve al recuperar. La recuperación manual de reservas antiguas cambia CREANDO a INCIERTO con auditoría; no libera la reserva ni vuelve a enviar. Se agregó una acción de recuperación al panel. No se agregó migración en esta etapa. Resultado de regresión ejecutada de forma aislada: 240 pruebas aprobadas, incluidas las pruebas PostgreSQL de Wompi; la suite separada de integración y concurrencia general PostgreSQL pasó 10 pruebas. La primera ejecución simultánea de ambas suites falló porque compartieron y limpiaron la misma base de prueba; la repetición secuencial pasó.

**Aún no está listo para desplegar:** no se ha realizado una prueba funcional integral de la interfaz ni una prueba completa de reinicio, caída antes/después del envío, respuesta tardía tras pérdida de conexión de coordinación y respuesta contradictoria. El bloqueo asesor depende de que todas las ejecuciones y recuperaciones usen este mismo protocolo; requiere revisión independiente antes de habilitarlo. Las afirmaciones históricas posteriores corresponden a estados anteriores.

**Avance de diagnóstico:** se agregó una consulta administrativa, con umbral configurable, que identifica reservas antiguas en CREANDO sin modificar su estado ni reenviarlas. La edad por sí sola no permite distinguir un proceso activo de uno caído. Las 14 pruebas focalizadas locales pasaron, incluida una reserva sintética antigua. No existe todavía el mecanismo distribuido necesario para comprobar actividad y cambiar con seguridad a INCIERTO; tampoco se han completado las pruebas de interrupción y del panel. No desplegar.

**Actualización de pruebas:** se adaptaron las cuatro pruebas antiguas incorporando la aprobación y conservando los escenarios de rechazo, timeout, duplicidad y fallo al guardar. Regresión SQLite: 232 aprobadas y 7 omitidas; las siete omitidas requerían PostgreSQL y se ejecutaron por separado: 7 aprobadas. Integración y concurrencia generales PostgreSQL: 10 aprobadas. Todas las bases fueron locales y los proveedores simulados. El contenedor es temporal. El panel ahora permite revisar detalle y auditoría, decisiones, ejecución y cotejo, pero faltan verificaciones integrales de interfaz y algunos escenarios de interrupción.

**Riesgo pendiente:** una caída abrupta después de reservar deja la operación en `CREANDO`; aunque la reserva impide reenvíos, todavía no existe un procedimiento automático comprobado que la reclasifique como `INCIERTO`. También se necesitan pruebas específicas de interrupción antes del envío, respuestas contradictorias y validación completa del panel. No se considera listo para despliegue. Los resultados de los párrafos siguientes son históricos.

**Actualización posterior:** se preparó ejecución compartida con reserva antes de HTTP y cotejo operativo. En pruebas locales: 13 pruebas focalizadas aprobadas; una prueba PostgreSQL de concurrencia aprobada con un único envío simulado. La última regresión general obtuvo 227 aprobadas, 7 omitidas y 4 fallidas: estas cuatro pruebas anteriores aún esperan que la ruta antigua ejecute sin aprobación y deben adaptarse sin perder cobertura. El panel y las pruebas integrales no están completos. El texto histórico siguiente describe un estado anterior y queda conservado como contexto. No desplegar todavía.

**Actualización provisional:** el usuario autorizó modificar la ruta anterior. En el código local ahora se bloquea toda ejecución por esa ruta con HTTP 409, como medida temporal; aún falta implementar el servicio común de autorización y habilitar la ejecución aprobada. Se ejecutaron 11 pruebas focalizadas satisfactoriamente; la suite histórica requiere adaptación porque antes esperaba que la ruta enviara reembolsos. No se ha desplegado este bloqueo.

**Avance del 13 de noviembre:** la creación de solicitudes libera la transacción antes de consultar Wompi y después vuelve a bloquear y validar el pago y la ausencia de solicitudes. Las 11 pruebas focalizadas pasaron. La prueba de concurrencia PostgreSQL y la regresión completa deben repetirse para este cambio; el informe de resultados anteriores no constituye evidencia del código actual.

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
