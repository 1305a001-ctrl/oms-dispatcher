"""Set required env vars so settings load without a real .env."""
import os

os.environ.setdefault(
    "AICORE_DB_URL", "postgresql://test:test@localhost:5432/test"
)
