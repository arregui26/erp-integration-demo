import time

import httpx
from pydantic import ValidationError

from erp_connector.contracts import Page


class SourceError(Exception):
    """Safe error code; never includes URLs, credentials or response bodies."""


class RestERPAdapter:
    def __init__(self, settings, client: httpx.Client, sleep=time.sleep):
        self.settings = settings
        self.client = client
        self.sleep = sleep
        self.requests = 0

    def fetch(self, cursor):
        for attempt in range(self.settings.retry_attempts):
            delay = min(2**attempt, 8)
            try:
                self.requests += 1
                response = self.client.get(
                    self.settings.erp_base_url + "/api/changes",
                    params={"after": cursor, "limit": self.settings.page_size},
                    headers={"X-ERP-Key": self.settings.erp_api_key.get_secret_value()},
                )
            except httpx.RequestError:
                code = "source_network_error"
            else:
                if response.status_code == 200:
                    try:
                        page = Page.model_validate(response.json())
                    except (ValueError, ValidationError):
                        raise SourceError("invalid_source_contract") from None
                    return page
                if response.status_code == 429:
                    code = "source_rate_limited"
                    try:
                        delay = max(1, int(response.headers.get("Retry-After", "1")))
                    except ValueError:
                        delay = 1
                    # Do not retry earlier than the provider requests; end this bounded run.
                    if delay > 30:
                        raise SourceError("source_rate_limited")
                elif response.status_code >= 500:
                    code = "source_unavailable"
                else:
                    raise SourceError("source_rejected")
            if attempt + 1 == self.settings.retry_attempts:
                raise SourceError(code)
            self.sleep(delay)
        raise AssertionError("Unreachable retry loop")
