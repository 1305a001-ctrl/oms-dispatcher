"""Dispatch-decision tests using a fake httpx transport so no real
HTTP, no real DB, no real services."""
from typing import Any
from uuid import uuid4

import httpx
import pytest

from oms_dispatcher.dispatcher import dispatch_one


def _intent(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": uuid4(),
        "venue": "binance",
        "asset": "BTC-USDT",
        "side": "buy",
        "notional_usd": 100.0,
        "qty": None,
        "idempotency_key": "test-strategy:test-alpha:entry",
    }
    base.update(overrides)
    return base


def _client_returning(status: int, body: dict[str, Any]) -> httpx.AsyncClient:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_close_side_rejected_without_position_context():
    decision = await dispatch_one(
        _client_returning(200, {}), _intent(side="close")
    )
    assert decision.outcome == "rejected"
    assert "close" in decision.reason


async def test_unknown_venue_rejected():
    decision = await dispatch_one(
        _client_returning(200, {}), _intent(venue="okx")
    )
    assert decision.outcome == "rejected"
    assert "no_adapter_for_venue" in decision.reason


async def test_missing_notional_rejected():
    decision = await dispatch_one(
        _client_returning(200, {}), _intent(notional_usd=None)
    )
    assert decision.outcome == "rejected"
    assert "missing_notional_usd" in decision.reason


async def test_adapter_accepted_returns_submitted():
    decision = await dispatch_one(
        _client_returning(
            200, {"accepted": True, "broker_order_id": "BX-12345"}
        ),
        _intent(),
    )
    assert decision.outcome == "submitted"
    assert decision.broker_order_id == "BX-12345"


async def test_adapter_not_accepted_returns_rejected():
    decision = await dispatch_one(
        _client_returning(200, {"accepted": False, "reason": "no_route"}),
        _intent(),
    )
    assert decision.outcome == "rejected"
    assert "no_route" in decision.reason


async def test_broker_502_includes_code_msg():
    decision = await dispatch_one(
        _client_returning(
            502,
            {
                "accepted": False,
                "broker_error_code": -2010,
                "broker_error_msg": "insufficient margin",
            },
        ),
        _intent(),
    )
    assert decision.outcome == "rejected"
    assert "broker:-2010" in decision.reason
    assert "insufficient margin" in decision.reason


async def test_adapter_4xx_rejected_not_retried():
    decision = await dispatch_one(
        _client_returning(400, {}), _intent()
    )
    assert decision.outcome == "rejected"
    assert "adapter_http_400" in decision.reason


async def test_adapter_5xx_transient_retry_later():
    decision = await dispatch_one(
        _client_returning(503, {}), _intent()
    )
    assert decision.outcome == "transient_error"
    assert "adapter_5xx_503" in decision.reason


async def test_connect_error_transient():
    def explode(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(explode))
    decision = await dispatch_one(client, _intent())
    assert decision.outcome == "transient_error"
    assert decision.reason == "ConnectError"


@pytest.mark.parametrize("venue", ["alpaca", "polymarket", "oanda"])
async def test_known_venues_have_adapter_urls(venue):
    """Smoke test that every wired venue has *some* URL defined."""
    decision = await dispatch_one(
        _client_returning(200, {"accepted": True, "broker_order_id": "X"}),
        _intent(venue=venue),
    )
    # Either submitted (mock accepts) or rejected with a non-no-adapter reason.
    assert decision.outcome != "rejected" or "no_adapter" not in (
        decision.reason or ""
    )
