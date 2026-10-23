import pytest
from pydantic import ValidationError

from erp_connector.config import Settings
from erp_connector.contracts import OrderData, ProductData


@pytest.mark.parametrize(
    "override", [{"stock": "-1"}, {"unit_price": "1.234"}, {"currency": "usd"}, {"sku": "bad id"}]
)
def test_invalid_product_data(override):
    data = {
        "sku": "TEST",
        "name": "Fictional",
        "unit_price": "1.00",
        "stock": "1",
        "currency": "USD",
    }
    with pytest.raises(ValidationError):
        ProductData.model_validate({**data, **override})


def test_order_quantity_must_be_positive():
    with pytest.raises(ValidationError):
        OrderData.model_validate(
            {
                "external_id": "TEST",
                "currency": "USD",
                "lines": [{"sku": "TEST", "quantity": "0", "unit_price": "1"}],
            }
        )


@pytest.mark.parametrize(
    "url",
    ["ftp://example.test", "https://user:secret@example.test", "http://example.test?token=secret"],
)
def test_source_url_cannot_embed_credentials(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_key="x" * 32, erp_api_key="y" * 32, erp_base_url=url)
