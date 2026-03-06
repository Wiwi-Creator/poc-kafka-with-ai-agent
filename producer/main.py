import json
import logging
import os
import time

from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Producer] %(message)s",
)
log = logging.getLogger(__name__)

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
TOPIC_NAME = os.getenv("TOPIC_NAME", "insurance-claims")


def create_producer(retries: int = 10, delay: int = 5) -> KafkaProducer:
    """Create KafkaProducer with retry logic for broker readiness."""
    for attempt in range(1, retries + 1):
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            log.info("Connected to Kafka at %s", KAFKA_BROKER)
            return producer
        except NoBrokersAvailable:
            log.warning(
                "Kafka not ready (attempt %d/%d), retrying in %ds...",
                attempt,
                retries,
                delay,
            )
            time.sleep(delay)
    raise RuntimeError(f"Failed to connect to Kafka after {retries} attempts")


DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "sample_claims.json")
PUBLISH_INTERVAL = int(os.getenv("PUBLISH_INTERVAL", "3"))


def load_claims(path: str) -> list[dict]:
    """Load claim records from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        claims = json.load(f)
    log.info("Loaded %d claims from %s", len(claims), path)
    return claims


def main():
    producer = create_producer()
    claims = load_claims(DATA_FILE)

    for i, claim in enumerate(claims, 1):
        producer.send(TOPIC_NAME, value=claim)
        producer.flush()
        log.info(
            "[%d/%d] Published %s (amount: %s) to [%s]",
            i,
            len(claims),
            claim["claim_id"],
            claim["claim_amount"],
            TOPIC_NAME,
        )
        if i < len(claims):
            time.sleep(PUBLISH_INTERVAL)

    log.info("All %d claims published. Producer exiting.", len(claims))


if __name__ == "__main__":
    main()
