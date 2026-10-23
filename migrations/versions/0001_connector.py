"""Local projections, checkpoint and synchronization audit."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "products",
        sa.Column("sku", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("stock", sa.Numeric(12, 3), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("source_sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint("unit_price >= 0"),
        sa.CheckConstraint("stock >= 0"),
    )
    op.create_table(
        "orders",
        sa.Column("external_id", sa.String(40), primary_key=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("lines", sa.JSON(), nullable=False),
        sa.Column("total", sa.Numeric(24, 2), nullable=False),
        sa.Column("source_sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint("total >= 0"),
    )
    op.create_table(
        "sync_checkpoint",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cursor", sa.Integer(), nullable=False),
        sa.Column("feed_id", sa.String(36)),
        sa.CheckConstraint("cursor >= 0"),
    )
    op.execute("INSERT INTO sync_checkpoint (id,cursor) VALUES (1,0)")
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("start_cursor", sa.Integer(), nullable=False),
        sa.Column("end_cursor", sa.Integer(), nullable=False),
        sa.Column("applied", sa.Integer(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('completed','partial','failed')"),
    )


def downgrade():
    for table in ("sync_runs", "sync_checkpoint", "orders", "products"):
        op.drop_table(table)
