import argparse
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
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "sample_claims.json")


def create_producer(retries: int = 10, delay: int = 5) -> KafkaProducer:
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


def load_claims(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        claims = json.load(f)
    log.info("Loaded %d claims from %s", len(claims), path)
    return claims


def main():
    parser = argparse.ArgumentParser(description="Send insurance claims to Kafka")
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Number of claims to send (default: all)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("PUBLISH_INTERVAL", "3")),
        help="Seconds between each claim (default: 3)",
    )
    args = parser.parse_args()

    producer = create_producer()
    all_claims = load_claims(DATA_FILE)
    claims = all_claims[: args.count] if args.count else all_claims

    log.info("Sending %d claim(s) with %.1fs interval to [%s]", len(claims), args.interval, TOPIC_NAME)

    for i, claim in enumerate(claims, 1):
        producer.send(TOPIC_NAME, value=claim)
        producer.flush()
        log.info(
            "[%d/%d] Published %s (amount: %s)",
            i,
            len(claims),
            claim["claim_id"],
            claim["claim_amount"],
        )
        if i < len(claims):
            time.sleep(args.interval)

    log.info("Done. %d claim(s) sent.", len(claims))


if __name__ == "__main__":
    main()
