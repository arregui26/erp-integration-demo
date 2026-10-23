import os

import pytest
from sqlalchemy import delete
from sqlalchemy.engine import make_url

from erp_connector.config import Settings
from erp_connector.database import Checkpoint, Order, Product, SyncRun, make_database

KEY = "test-connector-not-a-secret-1234567890"
ERP_KEY = "test-source-not-a-secret-123456789012"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None, api_key=KEY, erp_api_key=ERP_KEY, source_db_path=str(tmp_path / "source.db")
    )


@pytest.fixture
def pg(settings):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for PostgreSQL integration tests")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Only use a disposable database ending in _test")
    settings.database_url = url
    engine, sessions = make_database(url)
    with sessions.begin() as session:
        for model in (SyncRun, Order, Product):
            session.execute(delete(model))
        state = session.get(Checkpoint, 1)
        state.cursor = 0
        state.feed_id = None
    yield sessions, settings
    engine.dispose()
