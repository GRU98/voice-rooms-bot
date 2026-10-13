from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncEngine

from database.models import Base

log = logging.getLogger(__name__)


async def run_migrations(engine: AsyncEngine) -> None:
    """Create missing tables. Replace with Alembic when schema evolution is needed."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("Database schema is ready")
