"""Main dispatch loop.

Pure-ish: the per-intent dispatch logic is split into `dispatch_one`
which takes the HTTP client + intent dict and returns a Decision.
That makes it unit-testable without spinning up real services.
"""
import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from oms_dispatcher.adapters import adapter_url_for
from oms_dispatcher.db import db
from oms_dispatcher.settings import settings

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Decision:
    """What dispatcher decided to do with one intent."""
    outcome: str  # 'submitted' | 'rejected' | 'transient_error'
    broker_order_id: str | None = None
    reason: str | None = None


async def dispatch_one(
    http: httpx.AsyncClient, intent: dict[str, Any]
) -> Decision:
    """Decide what to do with one intent. No DB writes here."""
    venue = intent["venue"]
    side = intent["side"]
    intent_id = str(intent["id"])

    if side == "close":
        # 'close' alphas need position context to resolve buy/sell direction.
        # Right now neither oms-gateway nor we know the open position; defer
        # close-handling to v0.2 once the position-tracker lands.
        return Decision(outcome="rejected", reason="close_side_unsupported_v01")

    url = adapter_url_for(venue)
    if url is None:
        return Decision(
            outcome="rejected", reason=f"no_adapter_for_venue:{venue}"
        )

    if intent.get("notional_usd") is None:
        return Decision(outcome="rejected", reason="missing_notional_usd")

    payload = {
        "intent_id": intent_id,
        "asset": intent["asset"],
        "side": side,
        "notional_usd": intent["notional_usd"],
        "idempotency_key": intent["idempotency_key"],
    }

    try:
        resp = await http.post(f"{url}/orders/place", json=payload)
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
        log.warning(
            "dispatch.transient", intent_id=intent_id, venue=venue, err=str(exc)
        )
        return Decision(outcome="transient_error", reason=type(exc).__name__)

    if resp.status_code == 200:
        body = resp.json()
        if body.get("accepted") is True:
            return Decision(
                outcome="submitted",
                broker_order_id=body.get("broker_order_id"),
            )
        return Decision(
            outcome="rejected",
            reason=f"adapter_not_accepted:{body.get('reason', 'unknown')}",
        )

    if resp.status_code == 502:
        body = resp.json()
        code = body.get("broker_error_code")
        msg = (body.get("broker_error_msg") or "")[:120]
        return Decision(outcome="rejected", reason=f"broker:{code}:{msg}")

    # 4xx other than 502 = our request was malformed; don't retry forever.
    if 400 <= resp.status_code < 500:
        return Decision(
            outcome="rejected",
            reason=f"adapter_http_{resp.status_code}:{resp.text[:120]}",
        )

    # 5xx = adapter had a bad day, retry next cycle.
    log.warning(
        "dispatch.adapter_5xx",
        intent_id=intent_id,
        status=resp.status_code,
        body=resp.text[:200],
    )
    return Decision(
        outcome="transient_error", reason=f"adapter_5xx_{resp.status_code}"
    )


async def loop() -> None:
    log.info(
        "dispatcher.starting",
        poll_interval=settings.poll_interval_sec,
        batch_size=settings.batch_size,
    )

    async with httpx.AsyncClient(timeout=settings.adapter_timeout_sec) as http:
        while True:
            try:
                queued = await db.fetch_queued(settings.batch_size)
            except Exception:
                log.exception("dispatcher.fetch_failed")
                await asyncio.sleep(5)
                continue

            for intent in queued:
                intent_id = intent["id"]
                decision = await dispatch_one(http, intent)

                try:
                    if decision.outcome == "submitted":
                        await db.mark_submitted(
                            intent_id, decision.broker_order_id or "unknown"
                        )
                        log.info(
                            "intent.submitted",
                            intent_id=str(intent_id),
                            venue=intent["venue"],
                            broker_order_id=decision.broker_order_id,
                        )
                    elif decision.outcome == "rejected":
                        await db.mark_rejected(
                            intent_id, decision.reason or "unspecified"
                        )
                        log.info(
                            "intent.rejected",
                            intent_id=str(intent_id),
                            venue=intent["venue"],
                            reason=decision.reason,
                        )
                    else:
                        # transient_error → leave row in queued
                        log.info(
                            "intent.deferred",
                            intent_id=str(intent_id),
                            reason=decision.reason,
                        )
                except Exception:
                    log.exception(
                        "dispatcher.persist_failed", intent_id=str(intent_id)
                    )

            await asyncio.sleep(settings.poll_interval_sec)
