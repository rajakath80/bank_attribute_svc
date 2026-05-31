import json

from aiokafka import AIOKafkaConsumer

from app.core.config import settings
from app.core.engine import compute_attributes
from app.core.normalizer import normalize
from app.metrics.registry import metric_registry


async def consume():
    consumer = AIOKafkaConsumer(
        "raw_transactions",
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="attribute-service",
    )

    await consumer.start()

    async for msg in consumer:
        if msg is None or msg.value is None:
            continue

        batch = json.loads(msg.value)
        df = normalize(batch)
        compute_attributes(df, metric_registry.all())
