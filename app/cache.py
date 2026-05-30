import hashlib
import json
import logging
from typing import Any

from app.config import settings
from app.models import AttributeRequest

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis

    _REDIS_AVAILABLE = True
except ImportError:
    aioredis = None
    _REDIS_AVAILABLE = False
    logger.warning("redis package not installed - caching disabled")


class RedisCache:
    """
    Async Redis cache with transparent fallback to no-op when unavailable.
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._enabled = _REDIS_AVAILABLE and bool(settings.redis_url)

    async def connect(self) -> None:
        """Attempt to connect to Redis; log and disable on failure."""
        if not self._enabled:
            logger.info("Cache disabled (Redis not configured)")
            return
        try:
            if aioredis is None:
                raise RuntimeError("redis package not installed")
            self._client = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2,
            )
            await self._client.ping()
            logger.info("Redis connected: %s", settings.redis_url)
        except Exception as exc:
            logger.warning("Redis unavailable (%s) - cachind disabled", exc)
            self._client = None

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # public api
    def make_key(self, request: AttributeRequest) -> str:
        """
        Build a deterministic cache key from the request payload.

        Transactions are sorted by transaction_id before hashing so that
        submission order does not affect the key.
        """
        sorted_txns = sorted(
            (t.model_dump(mode="json") for t in request.transactions),
            key=lambda t: t["transaction_id"],
        )
        payload = json.dumps(sorted_txns, sort_keys=True, default=str)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        return f"bas:v1:{digest}"

    async def get(self, key: str) -> dict[str, Any] | None:
        """Return the cached value or None on miss / error."""
        if not self._client:
            return None
        try:
            raw = await self._client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning("Cache GET error: %s", exc)
            return None

    async def set(self, key: str, value: dict[str, Any], ttl: int = 300) -> None:
        """Store a value; silently ignore errors."""
        if not self._client:
            return
        try:
            await self._client.setex(key, ttl, json.dumps(value, default=str))
        except Exception as exc:
            logger.warning("Cache SET error: %s", exc)

    async def delete(self, key: str) -> None:
        """Remove a key; silently ignore errors."""
        if not self._client:
            return
        try:
            await self._client.delete(key)
        except Exception as exc:
            logger.warning("Cache DELETE error: %s", exc)


# Singleton
cache = RedisCache()
