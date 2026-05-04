"""Env-driven settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aicore_db_url: str

    # Adapter URLs by venue. Override via env: ADAPTER_URL_BINANCE=http://...
    # Comma-separated venue=url pairs in ADAPTER_URLS for bulk override.
    adapter_url_binance: str = "http://binance-adapter:8004"
    adapter_url_alpaca: str = "http://alpaca-adapter:8005"  # Phase 5
    adapter_url_polymarket: str = "http://poly-adapter:8006"  # Phase 7
    adapter_url_oanda: str = "http://oanda-adapter:8007"  # Phase 4

    # Polling cadence
    poll_interval_sec: float = 1.0
    batch_size: int = 25

    # Per-call HTTP timeout to the adapters
    adapter_timeout_sec: float = 15.0

    # Health endpoint
    http_host: str = "0.0.0.0"  # noqa: S104  — bound to 127.0.0.1 in compose
    http_port: int = 8005

    log_level: str = "INFO"


settings = Settings()  # type: ignore[call-arg]
