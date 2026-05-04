# oms-dispatcher

**Phase 2.5.** The bridge between oms-gateway and the per-venue broker adapters.

```
oms-gateway → oms_intents (status='queued')
                    │
                    │ poll every 1s, batch 25
                    ▼
              oms-dispatcher
                    │  POST {adapter}/orders/place
                    ▼
       binance-adapter / alpaca-adapter / poly-adapter / oanda-adapter
                    │
                    ▼
              broker venue
```

## What it does

Polls postgres for queued intents, looks up the adapter URL from `venue`,
POSTs the order. Updates the row to `submitted` (with `broker_order_id` and
`submitted_at`) on adapter accept, or `rejected` (with `rejection_reason`) on
adapter reject. Network errors leave the row queued for next-poll retry.

## Why a separate service

- **Decoupling.** oms-gateway only writes intents — it doesn't know about
  brokers. Dispatcher only reads intents — it doesn't know about preflight.
- **Adapters can be deployed/restarted independently.** Dispatcher tolerates
  adapter being down (transient_error → next poll).
- **One place to enforce per-venue rate limits, retries, idempotency.**

## Idempotency story

Two layers handle redelivery:
1. `oms_intents.idempotency_key` UNIQUE — set by oms-gateway, prevents
   double-write of the same alpha.
2. Adapter uses `intent_id` as `newClientOrderId` (Binance) /
   `client_order_id` (Alpaca, Polymarket) — so even if dispatcher crashes
   *after* the broker ack but before the DB update, the next attempt POSTs
   the same intent_id, broker returns the existing order, dispatcher
   records it as if first time.

## Status transitions written by dispatcher

| From | To | When |
|---|---|---|
| queued | submitted | adapter returned 200 with `accepted: true` |
| queued | rejected  | adapter returned 200 with `accepted: false`, OR adapter returned 502 (broker rejected), OR adapter returned 4xx (our request malformed), OR side='close' or no notional_usd or no adapter for venue |
| queued | (unchanged) | adapter returned 5xx, network error, or timeout — next poll retries |

The `filled` / `partial` transitions are written by the *adapter's* WS user-data
stream (Phase 3.5), not by dispatcher.

## Run

```bash
pip install -e '.[dev]'
ruff check src/ tests/
pytest -q       # 10 tests, all pure (httpx MockTransport, no real DB)
oms-dispatcher  # daemon
```

Required env (see `src/oms_dispatcher/settings.py` for full list):

- `AICORE_DB_URL`

Override adapter URLs as needed:

- `ADAPTER_URL_BINANCE` (default `http://binance-adapter:8004`)
- `ADAPTER_URL_ALPACA`, `ADAPTER_URL_POLYMARKET`, `ADAPTER_URL_OANDA`

## Health

`GET http://localhost:8005/health`
