from fastapi.testclient import TestClient

from erp_connector.contracts import Page
from erp_connector.simulator import FeedStore, create_app


def test_seed_pagination_and_restart_preserves_feed(settings):
    first = FeedStore(settings.source_db_path)
    p1 = first.page(0, 2)
    assert [item["sequence"] for item in p1["items"]] == [1, 2]
    assert p1["has_more"] is True
    second = FeedStore(settings.source_db_path)
    p2 = second.page(2, 2)
    assert p2["feed_id"] == p1["feed_id"]
    assert p2["next_cursor"] == 4
    assert p2["has_more"] is False
    assert second.page(4, 2)["items"] == []
    Page.model_validate(p2)


def test_simulator_auth_and_validation(settings):
    headers = {"X-ERP-Key": settings.erp_api_key.get_secret_value()}
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/api/changes").status_code == 401
        assert client.get("/api/changes?after=999", headers=headers).status_code == 409
        bad = {"sku": "TEST", "name": "Demo", "unit_price": "-1", "stock": "0", "currency": "USD"}
        assert client.post("/demo/products", headers=headers, json=bad).status_code == 422
        good = {**bad, "unit_price": "1.25"}
        assert client.post("/demo/products", headers=headers, json=good).json()["sequence"] == 5
        assert client.get("/api/changes?after=4", headers=headers).json()["next_cursor"] == 5
