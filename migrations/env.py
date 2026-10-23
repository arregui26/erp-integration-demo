from alembic import context
from sqlalchemy import create_engine, pool

from erp_connector.config import Settings
from erp_connector.database import Base

engine = create_engine(Settings().database_url, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
