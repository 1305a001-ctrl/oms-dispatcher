"""Venue → adapter URL registry.

Pure dict in v0.1; future versions can switch to service-discovery (consul,
mDNS) without touching dispatcher.py.
"""
from oms_dispatcher.settings import settings


def adapter_url_for(venue: str) -> str | None:
    """Return adapter base URL for a venue, or None if no adapter is wired.

    Returning None lets the dispatcher mark the intent rejected with a
    helpful reason rather than retrying forever against a missing service.
    """
    return {
        "binance": settings.adapter_url_binance,
        "alpaca": settings.adapter_url_alpaca,
        "polymarket": settings.adapter_url_polymarket,
        "oanda": settings.adapter_url_oanda,
        # OKX/Bybit deferred to a later session pending account access
        "okx": None,
        "bybit": None,
    }.get(venue)
