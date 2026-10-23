# ERP Integration Demo

**Un ERP ficticio y un conector que sincroniza productos y órdenes con una base local.**

Python · FastAPI · REST · PostgreSQL · SQLite · Docker · GitHub Actions

[![CI](https://github.com/arregui26/erp-integration-demo/actions/workflows/ci.yml/badge.svg)](https://github.com/arregui26/erp-integration-demo/actions/workflows/ci.yml)

*An independent portfolio project: a fictional ERP change feed, incremental synchronization,
transactional projections, retries, checkpoints and an auditable integration API.*

**No se conecta a SAP ni implementa OData.** Demuestra conceptos de integración mediante REST
con un origen simulado y datos totalmente ficticios. No contiene sistemas ni datos de empleadores.

## Qué demuestra

- Separación entre contrato de origen, adaptador HTTP y lógica de sincronización.
- Lectura paginada de cambios mediante un cursor persistente.
- Actualización o creación de productos y órdenes usando identificadores de negocio estables.
- Validación de cantidades, importes, moneda y referencias a productos.
- Reintentos de conexión, respuestas 5xx y límites 429.
- Transacciones y rollback: un dato inválido no deja una importación a medias ni avanza el cursor.
- Protección contra ejecuciones simultáneas e idempotencia por ejecución.
- Auditoría de resultados, migraciones y pruebas con PostgreSQL real.

## Arquitectura y alcance

```mermaid
flowchart LR
    U[Usuario / sistema cliente] -->|Clave + Idempotency-Key| API[API del conector]
    API --> SYNC[Sincronización acotada]
    SYNC --> AD[Adaptador REST con reintentos]
    AD -->|X-ERP-Key / cambios paginados| ERP[ERP ficticio]
    ERP --> SOURCE[(SQLite: historial de cambios)]
    SYNC --> TARGET[(PostgreSQL: productos y órdenes)]
    SYNC --> STATE[(Cursor + auditoría)]
```

El origen es la autoridad sobre los datos; el destino es un **modelo local de consulta**.
Esta primera versión es unidireccional y se ejecuta bajo demanda. No registra movimientos
de inventario ni descuenta stock al importar órdenes: replica las existencias informadas
por el ERP. No incluye un ERP completo, facturación, contabilidad ni resolución bidireccional
de conflictos.

## Ejecutar localmente

Requisitos: Git, Docker y Docker Compose. Ejemplos para Bash/WSL.

```bash
git clone https://github.com/arregui26/erp-integration-demo.git
cd erp-integration-demo
cp .env.example .env
docker compose up --build -d
docker compose ps
```

| Servicio | Dirección local |
|---|---|
| Documentación del conector | http://localhost:8010/docs |
| Documentación del ERP ficticio | http://localhost:8110/docs |
| PostgreSQL del destino | `localhost:5410` |

Los puertos se publican solo en `127.0.0.1`. Las claves del ejemplo son ficticias,
exclusivas de esta demostración local; no son credenciales de servicios reales.
Cada API tiene su propia clave y permite introducirla mediante **Authorize** en Swagger.

## Recorrido de demostración

El origen empieza con tres productos de oficina y una orden ficticia. Los precios y cantidades
son datos de ejemplo. La orden inicial tiene un total calculado de **19.50 USD**.

### 1. Sincronizar

```bash
export API_KEY=demo-connector-key-change-before-use-001
export ERP_API_KEY=demo-source-key-change-before-use-0001

curl -sS -X POST http://localhost:8010/v1/sync-runs \
  -H "X-API-Key: $API_KEY" \
  -H 'Idempotency-Key: demo-first-sync'
```

En una instalación nueva, la respuesta incluye:

```json
{
  "status": "completed",
  "start_cursor": 0,
  "end_cursor": 4,
  "applied": 4,
  "pages": 2,
  "requests": 2,
  "error_code": null
}
```

También devuelve el ID de ejecución y sus fechas. La llamada es síncrona: el `200` indica que
terminó una ejecución auditada; hay que comprobar `status`, que también puede ser `failed`
o `partial`. Una segunda ejecución con una nueva clave no duplica datos: si no hay cambios,
`applied` será cero. Repetir la misma clave devuelve la ejecución anterior con la cabecera
`Idempotency-Replayed: true`, sin consultar de nuevo el ERP.

### 2. Consultar el resultado

```bash
curl -sS http://localhost:8010/v1/products -H "X-API-Key: $API_KEY"
curl -sS http://localhost:8010/v1/orders -H "X-API-Key: $API_KEY"
curl -sS http://localhost:8010/v1/sync-runs/REEMPLAZA_CON_EL_ID \
  -H "X-API-Key: $API_KEY"
```

Los importes se serializan como cadenas decimales para conservar su precisión.
Las consultas de productos y órdenes aceptan `limit` (1 a 100) y `offset`.

### 3. Cambiar un producto en el ERP ficticio

```bash
curl -sS -X POST http://localhost:8110/demo/products \
  -H "X-ERP-Key: $ERP_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"sku":"DEMO-PEN","name":"Updated demo pen","unit_price":"2.00","stock":"90","currency":"USD","active":true}'

curl -sS -X POST http://localhost:8010/v1/sync-runs \
  -H "X-API-Key: $API_KEY" \
  -H 'Idempotency-Key: demo-price-update'
```

En el recorrido anterior se importa un solo cambio: el mismo producto se actualiza,
sin crear otra fila. El ERP también admite `POST /demo/orders` para generar cambios de órdenes.
Cada envío al simulador agrega un evento nuevo; el endpoint de edición del simulador no es
idempotente. La idempotencia del conector protege ejecuciones e identificadores de destino.

## Contratos de la API

| Endpoint | Acceso | Propósito |
|---|---|---|
| `GET /health/live` | Público | Comprobar proceso |
| `GET /health/ready` | Clave del conector | Comprobar DB y migración inicial |
| `POST /v1/sync-runs` | Clave + Idempotency-Key | Ejecutar sincronización |
| `GET /v1/sync-runs/{id}` | Clave del conector | Consultar auditoría |
| `GET /v1/products` | Clave del conector | Consultar productos replicados |
| `GET /v1/orders` | Clave del conector | Consultar órdenes replicadas |
| `GET /api/changes?after=0&limit=2` | Clave del ERP | Leer cambios del simulador |

El feed entrega un `feed_id`, eventos con secuencias crecientes, `next_cursor` y `has_more`.
El conector valida que el cursor coincida con el último evento y que una página no esté vacía
si afirma tener más elementos. Detecta el reemplazo del origen si cambia su `feed_id`.
El simulador conserva tanto los eventos como esa identidad en un volumen SQLite.

## Recuperación y garantías

- Las proyecciones y el cursor se confirman juntos, dentro de un savepoint. Un fallo conocido
  revierte todos los cambios de esa ejecución y conserva una fila de auditoría con el error.
- El límite `MAX_PAGES` produce una ejecución `partial`: lo importado se confirma y una nueva
  ejecución, con otra clave, continúa desde el cursor guardado.
- Un bloqueo transaccional de PostgreSQL impide dos sincronizaciones simultáneas en la misma
  instalación. Una llamada que encuentra el bloqueo ocupado recibe `409`; puede reintentarse.
- Una clave que terminó en fallo devuelve ese mismo fallo si se repite. Para intentar de nuevo
  después de corregir el problema, utiliza una **nueva** clave.
- Si el proceso cae, PostgreSQL revierte la transacción y libera el bloqueo. Puede que no quede
  una auditoría del intento interrumpido; el siguiente intento vuelve desde el último cursor confirmado.
- Un producto inexistente o una moneda incompatible en una orden detiene la ejecución. No se
  descartan registros inválidos silenciosamente.
- No se propagan eliminaciones físicas. Un producto puede desactivarse con `active: false`.

## Pruebas y calidad

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e .
ruff check .
ruff format --check .
pytest -q
```

Las pruebas de contrato, reintentos y simulador son locales. Las de transacciones y concurrencia
requieren PostgreSQL desechable, con un nombre de base terminado en `_test` y migraciones aplicadas:

```bash
export API_KEY=test-connector-not-a-secret-1234567890
export ERP_API_KEY=test-source-not-a-secret-123456789012
export DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5410/erp_demo_test
export TEST_DATABASE_URL="$DATABASE_URL"
alembic upgrade head
alembic check
pytest -q
```

Estas pruebas vacían las tablas de la base de pruebas. Nunca apuntes a datos que quieras conservar.
GitHub Actions crea PostgreSQL desechable, migra el esquema, ejecuta las pruebas y construye Docker.

## Seguridad y operación

- No hay credenciales reales, personas reales ni información empresarial en las fixtures.
- `.env`, bases de datos y archivos privados están excluidos de Git y del contexto Docker.
- Claves separadas para origen y conector; comparación constante. El cliente no puede elegir
  una URL de origen arbitraria: se configura una única dirección del lado del servidor.
- No se persisten respuestas HTTP crudas ni claves en la auditoría; se usan códigos de error propios.
- Contenedores de aplicación sin root ni capacidades adicionales, con archivos de solo lectura
  salvo el volumen de datos del simulador.
- Las instalaciones expuestas a Internet requieren claves propias, TLS, límites de tráfico y
  control de acceso. Este repositorio no despliega servicios públicos ni activa conexiones reales.

```bash
docker compose stop    # detiene sin borrar datos
docker compose up -d   # reinicia conservando origen, proyecciones y cursor
```

No uses `down -v` para conservar los datos. No borres solo el volumen del ERP: su identidad
cambiaría y el conector lo detectaría. Una recuperación real requiere restaurar un respaldo
consistente o planificar una nueva importación.

## Decisiones y evolución

Se eligió una transacción acotada para que la consistencia sea fácil de demostrar. El bloqueo
se mantiene durante la lectura HTTP; para cargas grandes conviene una cola y un modelo de
leases, métricas e importación por lotes. Consulta [arquitectura](docs/architecture.md).

**Carlos Arregui Torres** · [Perfil profesional](https://perfil.arregui26.chatgpt.site)
· [LinkedIn](https://linkedin.com/in/carlos-arregui-torres)

Licencia [MIT](LICENSE).
