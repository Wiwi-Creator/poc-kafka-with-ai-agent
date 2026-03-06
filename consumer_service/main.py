import json
import logging
import os
import time

from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import NoBrokersAvailable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ConsumerService] %(message)s",
)
log = logging.getLogger(__name__)

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
INPUT_TOPIC = os.getenv("INPUT_TOPIC", "insurance-claims")
PENDING_TOPIC = os.getenv("PENDING_TOPIC", "claims-pending")


def create_consumer(retries: int = 10, delay: int = 5) -> KafkaConsumer:
    for attempt in range(1, retries + 1):
        try:
            consumer = KafkaConsumer(
                INPUT_TOPIC,
                bootstrap_servers=KAFKA_BROKER,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                auto_offset_reset="earliest",
                group_id="consumer-service-group",
                enable_auto_commit=False,
            )
            log.info("Connected to Kafka at %s, subscribed to [%s]", KAFKA_BROKER, INPUT_TOPIC)
            return consumer
        except NoBrokersAvailable:
            log.warning("Kafka not ready (attempt %d/%d), retrying in %ds...", attempt, retries, delay)
            time.sleep(delay)
    raise RuntimeError(f"Failed to connect to Kafka after {retries} attempts")


def create_producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
    )


def main():
    consumer = create_consumer()
    producer = create_producer()

    log.info("Forwarding claims from [%s] → [%s]", INPUT_TOPIC, PENDING_TOPIC)

    for message in consumer:
        claim = message.value
        claim_id = claim.get("claim_id", "unknown")

        producer.send(PENDING_TOPIC, value=claim)
        producer.flush()
        consumer.commit()

        log.info("Forwarded %s → [%s]", claim_id, PENDING_TOPIC)


if __name__ == "__main__":
    main()
