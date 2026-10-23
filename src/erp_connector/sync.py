from decimal import Decimal, localcontext

from pydantic import ValidationError
from sqlalchemy import select, text

from erp_connector.contracts import OrderData, ProductData
from erp_connector.database import Checkpoint, Order, Product, SyncRun, utcnow
from erp_connector.source import SourceError

LOCK_ID = 8202610


class BusyError(Exception):
    pass


def apply_change(session, change):
    if change.entity == "product":
        data = ProductData.model_validate(change.data)
        session.merge(Product(**data.model_dump(), source_sequence=change.sequence))
    else:
        data = OrderData.model_validate(change.data)
        for line in data.lines:
            product = session.get(Product, line.sku)
            if product is None:
                raise SourceError("order_unknown_product")
            if product.currency != data.currency:
                raise SourceError("order_currency_mismatch")
        with localcontext() as ctx:
            ctx.prec = 40
            total = sum((line.quantity * line.unit_price for line in data.lines), Decimal(0))
            total = total.quantize(Decimal("0.01"))
        session.merge(
            Order(
                external_id=data.external_id,
                currency=data.currency,
                lines=[line.model_dump(mode="json") for line in data.lines],
                total=total,
                source_sequence=change.sequence,
            )
        )
    session.flush()


def synchronize(sessions, adapter, settings, key):
    """One bounded run, transaction-wide lock and a savepoint for all projection changes."""
    with sessions.begin() as session:
        if not session.scalar(text("SELECT pg_try_advisory_xact_lock(:id)"), {"id": LOCK_ID}):
            raise BusyError
        previous = session.scalar(select(SyncRun).where(SyncRun.idempotency_key == key))
        if previous:
            return previous, True
        checkpoint = session.get(Checkpoint, 1)
        if checkpoint is None:
            raise RuntimeError("Run database migrations first")
        run = SyncRun(
            idempotency_key=key,
            status="completed",
            start_cursor=checkpoint.cursor,
            end_cursor=checkpoint.cursor,
            applied=0,
            pages=0,
            requests=0,
        )
        session.add(run)
        session.flush()
        cursor = checkpoint.cursor
        pages = applied = 0
        try:
            with session.begin_nested():
                for _ in range(settings.max_pages):
                    page = adapter.fetch(cursor)
                    if checkpoint.feed_id and checkpoint.feed_id != str(page.feed_id):
                        raise SourceError("source_feed_changed")
                    if len(page.items) > settings.page_size:
                        raise SourceError("invalid_source_pagination")
                    previous_sequence = cursor
                    for change in page.items:
                        if change.sequence <= previous_sequence:
                            raise SourceError("source_sequence_not_increasing")
                        apply_change(session, change)
                        previous_sequence = change.sequence
                        applied += 1
                    if page.next_cursor != previous_sequence or (page.has_more and not page.items):
                        raise SourceError("invalid_source_pagination")
                    cursor = page.next_cursor
                    checkpoint.cursor = cursor
                    checkpoint.feed_id = str(page.feed_id)
                    pages += 1
                    if not page.has_more:
                        break
                run.status = "partial" if page.has_more else "completed"
                session.flush()
        except (SourceError, ValidationError) as error:
            run.status = "failed"
            run.error_code = str(error) if isinstance(error, SourceError) else "invalid_entity_data"
            applied = 0
            cursor = run.start_cursor
        run.end_cursor = cursor
        run.pages = pages
        run.applied = applied
        run.requests = adapter.requests
        run.finished_at = utcnow()
        session.flush()
        return run, False
