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

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.cache import cache
from app.core.config import settings
from app.integrations.kafka.producer import start_producer, stop_producer
from app.metrics.registry import metric_registry

# Logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s – %(message)s"
)
logger = logging.getLogger("bank-attr-svc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm up Redis connection and log registered metrics on startup"""
    logger.info("Starting bank-attribute-service v%s", settings.version)
    logger.info("Registered metrics: %s", [m.name for m in metric_registry.all()])
    await cache.connect()
    await start_producer()

    yield

    await stop_producer()
    await cache.disconnect()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Bank Attribute Service",
    description="High-throughput transaction -> ML feature pipeline",
    version=settings.version,
    lifespan=lifespan,
)

app.include_router(router)
