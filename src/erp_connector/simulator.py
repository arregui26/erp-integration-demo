"""Small fictional ERP with a durable SQLite change log; one Uvicorn worker."""

import json
import secrets
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import APIKeyHeader

from erp_connector.config import Settings
from erp_connector.contracts import OrderData, ProductData

SEED = [
    (
        "product",
        {
            "sku": "DEMO-PEN",
            "name": "Demo blue pen",
            "unit_price": "1.25",
            "stock": "100",
            "currency": "USD",
            "active": True,
        },
    ),
    (
        "product",
        {
            "sku": "DEMO-BOOK",
            "name": "Demo notebook",
            "unit_price": "3.50",
            "stock": "50",
            "currency": "USD",
            "active": True,
        },
    ),
    (
        "product",
        {
            "sku": "DEMO-BOX",
            "name": "Demo storage box",
            "unit_price": "8.00",
            "stock": "20",
            "currency": "USD",
            "active": True,
        },
    ),
    (
        "order",
        {
            "external_id": "DEMO-ORDER-001",
            "currency": "USD",
            "lines": [
                {"sku": "DEMO-PEN", "quantity": "10", "unit_price": "1.25"},
                {"sku": "DEMO-BOOK", "quantity": "2", "unit_price": "3.50"},
            ],
        },
    ),
]


class FeedStore:
    def __init__(self, path):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS metadata "
                "(id INTEGER PRIMARY KEY, feed_id TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS changes (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                "entity TEXT NOT NULL, data TEXT NOT NULL)"
            )
            connection.execute("BEGIN IMMEDIATE")
            fresh = connection.execute(
                "INSERT OR IGNORE INTO metadata VALUES (1, ?)", (str(uuid4()),)
            ).rowcount
            if fresh:
                connection.executemany(
                    "INSERT INTO changes(entity,data) VALUES (?,?)",
                    [(entity, json.dumps(data)) for entity, data in SEED],
                )

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def page(self, after, limit):
        with self.connection() as connection:
            connection.execute("BEGIN")
            feed_id = connection.execute("SELECT feed_id FROM metadata WHERE id=1").fetchone()[0]
            maximum = connection.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM changes"
            ).fetchone()[0]
            if after > maximum:
                raise HTTPException(409, "Cursor is ahead of the source feed")
            rows = connection.execute(
                "SELECT sequence,entity,data FROM changes WHERE sequence>? "
                "ORDER BY sequence LIMIT ?",
                (after, limit),
            ).fetchall()
            cursor = rows[-1][0] if rows else after
            return {
                "feed_id": feed_id,
                "items": [
                    {"sequence": seq, "entity": entity, "data": json.loads(data)}
                    for seq, entity, data in rows
                ],
                "next_cursor": cursor,
                "has_more": cursor < maximum,
            }

    def append(self, entity, data):
        with self.connection() as connection:
            result = connection.execute(
                "INSERT INTO changes(entity,data) VALUES (?,?)", (entity, json.dumps(data))
            )
            return {"sequence": result.lastrowid, "entity": entity}


def create_app(settings=None):
    settings = settings or Settings()
    store = FeedStore(settings.source_db_path)

    @asynccontextmanager
    async def lifespan(app):
        yield

    app = FastAPI(
        title="Fictional ERP Simulator",
        version="0.1.0",
        lifespan=lifespan,
        description="Synthetic products and orders. No real ERP or company data.",
    )
    security = APIKeyHeader(name="X-ERP-Key", auto_error=False)

    def authorize(value: Annotated[str | None, Depends(security)]):
        if value is None or not secrets.compare_digest(
            value.encode(), settings.erp_api_key.get_secret_value().encode()
        ):
            raise HTTPException(401, "Invalid ERP key")

    @app.get("/health/live")
    def live():
        return {"status": "ok", "data": "fictional"}

    @app.get("/api/changes", dependencies=[Depends(authorize)])
    def changes(
        after: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=100)] = 2
    ):
        return store.page(after, limit)

    @app.post("/demo/products", dependencies=[Depends(authorize)], status_code=201)
    def change_product(body: ProductData):
        return store.append("product", body.model_dump(mode="json"))

    @app.post("/demo/orders", dependencies=[Depends(authorize)], status_code=201)
    def change_order(body: OrderData):
        return store.append("order", body.model_dump(mode="json"))

    return app
