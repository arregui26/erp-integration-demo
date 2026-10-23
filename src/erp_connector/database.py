from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    Numeric,
    String,
    Uuid,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (CheckConstraint("unit_price >= 0"), CheckConstraint("stock >= 0"))
    sku: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    stock: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    currency: Mapped[str] = mapped_column(String(3))
    active: Mapped[bool] = mapped_column(Boolean)
    source_sequence: Mapped[int] = mapped_column(Integer)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (CheckConstraint("total >= 0"),)
    external_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))
    lines: Mapped[list] = mapped_column(JSON)
    total: Mapped[Decimal] = mapped_column(Numeric(24, 2))
    source_sequence: Mapped[int] = mapped_column(Integer)


class Checkpoint(Base):
    __tablename__ = "sync_checkpoint"
    __table_args__ = (CheckConstraint("cursor >= 0"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    feed_id: Mapped[str | None] = mapped_column(String(36))


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (CheckConstraint("status IN ('completed','partial','failed')"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(16))
    start_cursor: Mapped[int] = mapped_column(Integer)
    end_cursor: Mapped[int] = mapped_column(Integer)
    applied: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def make_database(url):
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        raise ValueError("The connector requires PostgreSQL")
    return engine, sessionmaker(engine, expire_on_commit=False)
