import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from erp_connector.api import create_app
from erp_connector.contracts import Page
from erp_connector.database import Checkpoint, Order, Product, SyncRun
from erp_connector.simulator import FeedStore
from erp_connector.source import SourceError
from erp_connector.sync import BusyError, synchronize

pytestmark = pytest.mark.postgres


class Adapter:
    def __init__(self, store, page_size=2, transform=None):
        self.store = store
        self.requests = 0
        self.page_size = page_size
        self.transform = transform

    def fetch(self, cursor):
        self.requests += 1
        payload = self.store.page(cursor, self.page_size)
        if self.transform:
            payload = self.transform(payload)
        return Page.model_validate(payload)


def test_full_sync_and_two_kinds_of_idempotency(pg):
    sessions, settings = pg
    store = FeedStore(settings.source_db_path)
    first, replay = synchronize(sessions, Adapter(store), settings, "first")
    assert (first.status, first.applied, first.end_cursor, replay) == ("completed", 4, 4, False)
    duplicate, replay = synchronize(sessions, Adapter(store), settings, "first")
    assert duplicate.id == first.id and replay
    second, _ = synchronize(sessions, Adapter(store), settings, "second")
    assert second.applied == 0
    with sessions() as session:
        assert len(session.scalars(select(Product)).all()) == 3
        order = session.scalars(select(Order)).one()
        assert order.total == Decimal("19.50")


def test_incremental_update_overwrites_without_duplicate(pg):
    sessions, settings = pg
    store = FeedStore(settings.source_db_path)
    synchronize(sessions, Adapter(store), settings, "initial")
    store.append(
        "product",
        {
            "sku": "DEMO-PEN",
            "name": "Updated demo pen",
            "unit_price": "2.00",
            "stock": "90",
            "currency": "USD",
        },
    )
    run, _ = synchronize(sessions, Adapter(store), settings, "update")
    assert (run.applied, run.end_cursor) == (1, 5)
    with sessions() as session:
        product = session.get(Product, "DEMO-PEN")
        assert (product.unit_price, product.stock) == (Decimal("2.00"), Decimal("90.000"))


def test_invalid_later_page_rolls_back_all_changes(pg):
    sessions, settings = pg
    store = FeedStore(settings.source_db_path)

    def corrupt(page):
        if page["next_cursor"] == 4:
            page["items"][0]["data"]["stock"] = "-1"
        return page

    run, _ = synchronize(sessions, Adapter(store, transform=corrupt), settings, "invalid")
    assert (run.status, run.applied, run.end_cursor) == ("failed", 0, 0)
    assert run.error_code == "invalid_entity_data"
    with sessions() as session:
        assert session.get(Checkpoint, 1).cursor == 0
        assert session.scalar(select(Product)) is None
        assert session.get(SyncRun, run.id).status == "failed"
    recovered, _ = synchronize(sessions, Adapter(store), settings, "fixed-new-key")
    assert recovered.status == "completed"


def test_missing_product_order_rejected(pg):
    sessions, settings = pg
    store = FeedStore(settings.source_db_path)
    store.append(
        "order",
        {
            "external_id": "BAD-ORDER",
            "currency": "USD",
            "lines": [{"sku": "MISSING", "quantity": "1", "unit_price": "1"}],
        },
    )
    run, _ = synchronize(sessions, Adapter(store), settings, "bad-reference")
    assert run.error_code == "order_unknown_product"
    with sessions() as session:
        assert session.get(Checkpoint, 1).cursor == 0


def test_bounded_run_can_resume(pg):
    sessions, settings = pg
    store = FeedStore(settings.source_db_path)
    settings.max_pages = 1
    first, _ = synchronize(sessions, Adapter(store), settings, "part-one")
    assert (first.status, first.end_cursor) == ("partial", 2)
    second, _ = synchronize(sessions, Adapter(store), settings, "part-two")
    assert (second.status, second.end_cursor) == ("completed", 4)


@pytest.mark.parametrize("broken", ["cursor", "sequence", "empty"])
def test_broken_pagination_cannot_advance_checkpoint(pg, broken):
    sessions, settings = pg
    store = FeedStore(settings.source_db_path)

    def corrupt(page):
        if broken == "cursor":
            page["next_cursor"] = 999
        elif broken == "sequence":
            page["items"][1]["sequence"] = page["items"][0]["sequence"]
        else:
            page["items"] = []
            page["next_cursor"] = 0
            page["has_more"] = True
        return page

    run, _ = synchronize(sessions, Adapter(store, transform=corrupt), settings, "broken")
    assert run.status == "failed" and run.end_cursor == 0


def test_feed_replacement_is_detected(pg, tmp_path):
    sessions, settings = pg
    synchronize(sessions, Adapter(FeedStore(settings.source_db_path)), settings, "initial")
    new_feed = FeedStore(str(tmp_path / "replacement.db"))
    run, _ = synchronize(sessions, Adapter(new_feed), settings, "replacement")
    assert run.error_code == "source_feed_changed"
    assert run.end_cursor == 4


def test_source_failure_is_audited(pg):
    sessions, settings = pg

    class Failing:
        requests = 3

        def fetch(self, cursor):
            raise SourceError("source_unavailable")

    run, _ = synchronize(sessions, Failing(), settings, "failed")
    assert (run.status, run.requests, run.error_code) == ("failed", 3, "source_unavailable")


def test_concurrent_sync_is_rejected(pg):
    sessions, settings = pg
    store = FeedStore(settings.source_db_path)
    acquired = threading.Event()
    release = threading.Event()

    class Slow(Adapter):
        def fetch(self, cursor):
            acquired.set()
            assert release.wait(5)
            return super().fetch(cursor)

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(synchronize, sessions, Slow(store), settings, "first")
        try:
            assert acquired.wait(5)
            with pytest.raises(BusyError):
                synchronize(sessions, Adapter(store), settings, "overlap")
        finally:
            release.set()
        assert first.result(timeout=5)[0].status == "completed"


def test_http_auth_sync_and_projection_queries(pg):
    _, settings = pg
    store = FeedStore(settings.source_db_path)
    app = create_app(settings, adapter_factory=lambda: Adapter(store))
    headers = {"X-API-Key": settings.api_key.get_secret_value(), "Idempotency-Key": "http"}
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/v1/products").status_code == 401
        assert client.get("/health/ready", headers=headers).status_code == 200
        run = client.post("/v1/sync-runs", headers=headers)
        assert run.status_code == 200 and run.json()["status"] == "completed"
        replay = client.post("/v1/sync-runs", headers=headers)
        assert replay.headers["Idempotency-Replayed"] == "true"
        assert len(client.get("/v1/products", headers=headers).json()) == 3
        assert client.get("/v1/orders", headers=headers).json()[0]["total"] == "19.50"
        assert client.get(f"/v1/sync-runs/{run.json()['id']}", headers=headers).status_code == 200
