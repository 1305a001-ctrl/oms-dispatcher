"""oms-dispatcher — Phase 2.5 of the trading stack.

Sits between oms-gateway (which writes queued intents) and the per-venue
broker adapters (binance-adapter, alpaca-adapter, ...).

Loop:
    SELECT * FROM oms_intents WHERE status='queued' ORDER BY created_at LIMIT N
    for each intent:
        adapter_url = adapters[venue]
        resp = POST adapter_url/orders/place {...}
        if resp.accepted:
            UPDATE oms_intents SET status='submitted', broker_order_id=...,
                                   submitted_at=now() WHERE id=...
        else:
            UPDATE oms_intents SET status='rejected',
                                   rejection_reason='broker:<code>:<msg>',
                                   completed_at=now() WHERE id=...

Network errors leave the row queued; next poll retries. Adapter is the
idempotency anchor — if dispatcher crashes after the broker ack but
before the DB write, the next attempt POSTs the same intent_id (used as
broker newClientOrderId), broker returns the existing order, dispatcher
records it as if first time.
"""

__version__ = "0.1.0"
