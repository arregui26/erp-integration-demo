import httpx
import pytest

from erp_connector.source import RestERPAdapter, SourceError

FEED = "00000000-0000-0000-0000-000000000001"


def page():
    return {"feed_id": FEED, "items": [], "next_cursor": 0, "has_more": False}


def test_retry_503_then_success(settings):
    calls = []
    delays = []

    def respond(request):
        calls.append(request)
        assert request.headers["X-ERP-Key"] == settings.erp_api_key.get_secret_value()
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json=page())

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        adapter = RestERPAdapter(settings, client, sleep=delays.append)
        assert adapter.fetch(0).next_cursor == 0
        assert adapter.requests == 2
    assert delays == [1]


def test_network_retry_exhaustion_sanitized(settings):
    def fail(request):
        raise httpx.ConnectError("sensitive provider error")

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        adapter = RestERPAdapter(settings, client, sleep=lambda _: None)
        with pytest.raises(SourceError, match="^source_network_error$"):
            adapter.fetch(0)
        assert adapter.requests == 3


def test_unauthorized_not_retried(settings):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401))) as client:
        adapter = RestERPAdapter(settings, client)
        with pytest.raises(SourceError, match="^source_rejected$"):
            adapter.fetch(0)
        assert adapter.requests == 1


@pytest.mark.parametrize("delay,expected_requests", [("2", 3), ("120", 1)])
def test_rate_limit_honored(settings, delay, expected_requests):
    waits = []
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": delay}))
    ) as client:
        adapter = RestERPAdapter(settings, client, sleep=waits.append)
        with pytest.raises(SourceError, match="^source_rate_limited$"):
            adapter.fetch(0)
        assert adapter.requests == expected_requests
    assert waits == ([2, 2] if delay == "2" else [])


@pytest.mark.parametrize("body", [{}, {**page(), "feed_id": "bad"}, []])
def test_invalid_contract_rejected(settings, body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as client:
        with pytest.raises(SourceError, match="^invalid_source_contract$"):
            RestERPAdapter(settings, client).fetch(0)
