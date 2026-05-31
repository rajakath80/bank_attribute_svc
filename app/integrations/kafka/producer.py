import json
import logging

from aiokafka import AIOKafkaProducer

from app.core.config import settings

logger = logging.getLogger(__name__)

producer = None


async def start_producer():
    global producer
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
    )
    await producer.start()
    logger.info("Kafka producer started")


async def stop_producer():
    global producer
    if producer is not None:
        await producer.stop()
        producer = None
        logger.info("Kafka producer stopped")


async def send_batch(transactions: list):
    if producer is None:
        return

    await producer.send("raw_transactions", json.dumps(transactions).encode())
