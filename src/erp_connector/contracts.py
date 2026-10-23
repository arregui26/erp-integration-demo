from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r"^[A-Z0-9_-]{1,40}$")]
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Quantity = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3)]


class ProductData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: Identifier
    name: str = Field(min_length=1, max_length=120)
    unit_price: Money
    stock: Quantity
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    active: bool = True


class OrderLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: Identifier
    quantity: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]
    unit_price: Money


class OrderData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_id: Identifier
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    lines: list[OrderLine] = Field(min_length=1, max_length=50)


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(gt=0)
    entity: Literal["product", "order"]
    data: dict


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feed_id: UUID
    items: list[Change] = Field(max_length=100)
    next_cursor: int = Field(ge=0)
    has_more: bool
