"""Postgres pool — reads queued intents, writes submission state."""
from typing import Any
from uuid import UUID

import asyncpg
import structlog

from oms_dispatcher.settings import settings

log = structlog.get_logger(__name__)


class DB:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("DB not connected — call connect() first")
        return self._pool

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            settings.aicore_db_url, min_size=1, max_size=4
        )
        log.info("db.connected", url=settings.aicore_db_url.split("@")[-1])

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    async def fetch_queued(self, limit: int) -> list[dict[str, Any]]:
        """Pull queued intents oldest-first."""
        rows = await self.pool.fetch(
            """
            SELECT id, venue, asset, side, notional_usd, qty, idempotency_key
            FROM oms_intents
            WHERE status = 'queued'
            ORDER BY created_at
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]

    async def mark_submitted(
        self, intent_id: UUID, broker_order_id: str
    ) -> None:
        await self.pool.execute(
            """
            UPDATE oms_intents
            SET status = 'submitted',
                broker_order_id = $2,
                submitted_at = now()
            WHERE id = $1 AND status = 'queued'
            """,
            intent_id,
            broker_order_id,
        )

    async def mark_rejected(
        self, intent_id: UUID, reason: str
    ) -> None:
        await self.pool.execute(
            """
            UPDATE oms_intents
            SET status = 'rejected',
                rejection_reason = $2,
                completed_at = now()
            WHERE id = $1 AND status = 'queued'
            """,
            intent_id,
            reason,
        )


db = DB()
