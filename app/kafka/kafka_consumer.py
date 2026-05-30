import json

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.engine import compute_attributes
from app.normalizer import normalize
from app.registry import metric_registry


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
