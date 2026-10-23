# Decisiones del conector

## Una sola dirección y una autoridad de datos

El ERP ficticio es la fuente. PostgreSQL contiene una proyección para consultas. Importar
una orden no cambia las existencias: ese cambio debe venir informado por el ERP. Así no se
mezcla una demostración de integración con reglas completas de inventario o contabilidad.

## Adaptador separado

`RestERPAdapter.fetch(cursor)` es el límite entre transporte y sincronización. El resto del
conector opera con un contrato tipado, no con respuestas JSON sin validar. Un adaptador para
un ERP real necesitaría autenticación, mapeo y pruebas específicas de ese producto. Este
proyecto no implementa SAP, OData, OAuth ni un contrato compatible con marcas concretas.

## Identidad, cursor e idempotencia

- La identidad del feed evita continuar desde un cursor perteneciente a otro origen.
- La secuencia del evento determina el orden de aplicación.
- SKU y external_id identifican las entidades en destino. Reimportarlas actualiza filas.
- Idempotency-Key identifica una ejecución, con alcance global en esta instalación.
- Los datos se aplican en orden; los productos referenciados deben existir antes de la orden.

La detección de secuencias crecientes no verifica criptográficamente la integridad del origen.
Se confía en que el servidor configurado entrega su historial completo conforme al contrato.

## Consistencia y errores

Una transacción exterior toma un advisory lock e inserta el registro de ejecución. Un savepoint
encierra proyecciones y checkpoint. Un error de datos o de origen revierte ese savepoint;
la transacción exterior confirma la auditoría del fallo. Un error de base de datos no manejado
revierte toda la transacción y produce un error del servicio, sin fingir una ejecución exitosa.

Los reintentos se limitan a lecturas HTTP, que no modifican el origen. Las respuestas 4xx no se
reintentan, salvo 429. Si Retry-After supera 30 segundos se termina la ejecución sin anticipar
el reintento pedido por el servidor. El operador puede volver a ejecutar después.

## Límites operativos

La API ejecuta el trabajo de forma síncrona, con tiempo de espera de red de cinco segundos,
máximo de intentos y páginas. Mantiene una conexión PostgreSQL durante las llamadas HTTP;
es una decisión adecuada para esta demo pequeña, no un diseño de integración de alto volumen.
Los timeouts del cliente pueden ocurrir antes del final: se debe consultar o reintentar con la
misma clave cuando el bloqueo se libere. No hay scheduler, cola, múltiples fuentes, borrado
físico, conciliación automática ni panel de administración.

El feed SQLite persiste en un volumen y se inicializa con datos sintéticos una sola vez.
Las rutas `/demo/*` representan cambios del ERP y solo sirven para ensayar la integración.

## Referencias

- https://www.postgresql.org/docs/current/explicit-locking.html
- https://docs.sqlalchemy.org/en/20/orm/session_transaction.html
- https://fastapi.tiangolo.com/advanced/testing-events/
