import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from erp_connector.config import Settings
from erp_connector.database import Checkpoint, Order, Product, SyncRun, make_database
from erp_connector.source import RestERPAdapter
from erp_connector.sync import BusyError, synchronize


class RunOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    start_cursor: int
    end_cursor: int
    applied: int
    pages: int
    requests: int
    error_code: str | None
    created_at: datetime
    finished_at: datetime


class ProductOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    sku: str
    name: str
    unit_price: Decimal
    stock: Decimal
    currency: str
    active: bool
    source_sequence: int


class OrderOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    external_id: str
    currency: str
    lines: list[dict]
    total: Decimal
    source_sequence: int


def create_app(settings=None, adapter_factory=None):
    settings = settings or Settings()
    engine, sessions = make_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(
        title="ERP Integration Connector",
        version="0.1.0",
        lifespan=lifespan,
        description="Fictional ERP → local read model. Not a SAP/OData connector.",
    )
    app.state.sessions = sessions
    app.state.engine = engine
    security = APIKeyHeader(name="X-API-Key", auto_error=False)

    def authorize(value: Annotated[str | None, Depends(security)]):
        if value is None or not secrets.compare_digest(
            value.encode(), settings.api_key.get_secret_value().encode()
        ):
            raise HTTPException(401, "Invalid API key")

    auth = [Depends(authorize)]

    @app.get("/health/live", tags=["Health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", dependencies=auth, tags=["Health"])
    def ready():
        try:
            with sessions() as session:
                state = session.get(Checkpoint, 1)
                if state is None:
                    raise RuntimeError
        except Exception:
            raise HTTPException(503, "Database or migrations unavailable") from None
        return {"status": "ready"}

    @app.post("/v1/sync-runs", dependencies=auth, response_model=RunOutput, tags=["Sync"])
    def start_sync(
        response: Response,
        idempotency_key: Annotated[
            str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
        ],
    ):
        try:
            with httpx.Client(timeout=5, follow_redirects=False) as client:
                adapter = adapter_factory() if adapter_factory else RestERPAdapter(settings, client)
                result, replay = synchronize(sessions, adapter, settings, idempotency_key)
        except BusyError:
            raise HTTPException(409, "A synchronization is already running; retry later") from None
        response.headers["Idempotency-Replayed"] = str(replay).lower()
        return result

    @app.get("/v1/sync-runs/{run_id}", dependencies=auth, response_model=RunOutput, tags=["Sync"])
    def get_run(run_id: UUID):
        with sessions() as session:
            run = session.get(SyncRun, run_id)
            if run is None:
                raise HTTPException(404, "Sync run not found")
            return run

    @app.get("/v1/products", dependencies=auth, response_model=list[ProductOutput], tags=["Data"])
    def products(
        limit: Annotated[int, Query(ge=1, le=100)] = 20, offset: Annotated[int, Query(ge=0)] = 0
    ):
        with sessions() as session:
            return session.scalars(
                select(Product).order_by(Product.sku).limit(limit).offset(offset)
            ).all()

    @app.get("/v1/orders", dependencies=auth, response_model=list[OrderOutput], tags=["Data"])
    def orders(
        limit: Annotated[int, Query(ge=1, le=100)] = 20, offset: Annotated[int, Query(ge=0)] = 0
    ):
        with sessions() as session:
            return session.scalars(
                select(Order).order_by(Order.external_id).limit(limit).offset(offset)
            ).all()

    return app
