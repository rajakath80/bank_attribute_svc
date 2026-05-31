"""
bank-attribute-service · FastAPI entry point
============================================
Exposes a single POST /attributes endpoint that accepts a batch of raw
transactions, normalises them, computes all registered metrics via the
Polars engine, optionally caches results in Redis, and returns a flat
attribute map per account.

Design goals
------------
* Sub-4 s on 100 k records (Polars lazy evaluation + Redis short-circuit)
* Deterministic output: same input → same output, always
* Zero-config metric registration: drop a new Metric subclass in registry.py
"""

import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi_limiter.depends import RateLimiter
from pyrate_limiter import Duration, Limiter, Rate

from app.cache import cache
from app.core.config import settings
from app.core.engine import compute_attributes_async
from app.core.normalizer import normalize
from app.core.scorer import score_account
from app.integrations.kafka.producer import send_batch
from app.integrations.plaid.adapter import (
    extract_balance_features,
    plaid_to_attribute_request,
)
from app.integrations.plaid.client import (
    fetch_plaid_transactions,
    get_sandbox_access_token,
)
from app.metrics.registry import metric_registry
from app.models import AttributeRequest, AttributeResponse

# Logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s – %(message)s"
)
logger = logging.getLogger("bank-attr-svc")


router = APIRouter()


@router.get("/health")
async def health():
    """Livness probe - returns 200 when service is up"""
    return {"status": "ok", "version": settings.version}


@router.post(
    "/attributes",
    dependencies=[Depends(RateLimiter(limiter=Limiter(Rate(2, Duration.SECOND * 5))))],
    response_model=AttributeResponse,
)
async def attributes(request: AttributeRequest):
    """
    Compute per-account attributes from a batch of raw transactions.

    Flow
    ----
    1. Build a deterministic cache key from the sorted transaction payload.
    2. Return cached result if present (Redis HIT).
    3. Normalise raw rows (dedup, dtype enforcement).
    4. Run Polars computation engine over all registered metrics.
    5. Store result in Redis with configured TTL.
    6. Return attribute map + timing metadata.
    """
    wall_start = time.perf_counter()

    # 1. Cache lookup
    cache_key = cache.make_key(request)
    cached = await cache.get(cache_key)
    if cached is not None:
        elapsed = time.perf_counter() - wall_start
        logger.info("Cache HIT 0 %.3f s", elapsed)
        cached["meta"]["cache_hit"] = True
        cached["meta"]["elapsed_seconds"] = round(elapsed, 4)
        return cached

    # 2. Normalise
    try:
        df = normalize(request.transactions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    row_count = len(df)
    logger.info(
        "Normalised %d transactions for %d accounts",
        row_count,
        df["account_id"].n_unique(),
    )

    # 3. Compute
    try:
        attribute_map = await compute_attributes_async(df, metric_registry.all())
    except Exception as exc:
        logger.exception("Engine Failure")
        raise HTTPException(status_code=500, detail="Computation failed") from exc

    elapsed = time.perf_counter() - wall_start
    logger.info("Computed %d attribute vectors in %.3f s", len(attribute_map), elapsed)

    # 4. Build response
    response_payload = {
        "attributes": attribute_map,
        "meta": {
            "transaction_count": row_count,
            "account_count": len(attribute_map),
            "metrics_computed": [m.name for m in metric_registry.all()],
            "elapsed_seconds": round(elapsed, 4),
            "cache_hit": False,
        },
    }

    # 5. Kafka - fire and forget
    asyncio.create_task(
        send_batch([t.model_dump(mode="json") for t in request.transactions])
    )

    # 6. Cache store
    await cache.set(cache_key, response_payload, ttl=settings.cache_ttl_seconds)

    return response_payload


@router.get("/demo/plaid")
async def demo_plaid():
    """
    End-to-end Plaid demo endpoint.
    1. Creates sandbox access token (simulates Link UI OAuth)
    2. Fetches real Plaid sandbox transactions
    3. Runs full attribute pipeline
    4. Returns attribute vectors + balance features
    """
    # 1. Get sandbox token (replaces link UI in production)
    access_token = get_sandbox_access_token()

    # 2. Fetch from Plaid
    plaid_response = fetch_plaid_transactions(access_token, days_back=90)

    # 3. Extract balance features (overdraft risk signal)
    balance_features = extract_balance_features(plaid_response)

    # 4. Run attribute pipeline
    request = plaid_to_attribute_request(plaid_response)
    if not request.transactions:
        raise HTTPException(status_code=422, detail="No transactions from Plaid")

    df = normalize(request.transactions)
    attribute_map = await compute_attributes_async(df, metric_registry.all())

    # 5. Inject balance features into attribute map
    for account_id, attrs in attribute_map.items():
        if account_id in balance_features:
            attrs["balance"] = balance_features[account_id]
        attrs["risk"] = score_account(attrs)

    return {
        "source": "plaid_sandbox",
        "attributes": attribute_map,
        "meta": {
            "transaction_count": len(request.transactions),
            "account_count": len(attribute_map),
            "plaid_env": settings.plaid_env,
        },
    }
