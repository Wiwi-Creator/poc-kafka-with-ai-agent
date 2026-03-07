import asyncio
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone

from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import NoBrokersAvailable

from orchestrator import process_claim
from token_tracker import tracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AIAgentService] %(message)s",
)
log = logging.getLogger(__name__)

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
INPUT_TOPIC = os.getenv("INPUT_TOPIC", "claims-pending")
OUTPUT_TOPIC = os.getenv("OUTPUT_TOPIC", "claim-results")
RESULTS_DIR = os.getenv("RESULTS_DIR", "/app/results")
RESULTS_FILE = os.path.join(RESULTS_DIR, "predictions.json")


def create_consumer(retries: int = 10, delay: int = 5) -> KafkaConsumer:
    """Create KafkaConsumer with retry logic for broker readiness."""
    for attempt in range(1, retries + 1):
        try:
            consumer = KafkaConsumer(
                INPUT_TOPIC,
                bootstrap_servers=KAFKA_BROKER,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                auto_offset_reset="earliest",
                group_id="ai-agent-service-group",
                consumer_timeout_ms=-1,
                max_poll_interval_ms=600000,  # 10 min, covers single claim LLM processing (~30-60s)
            )
            log.info("Connected to Kafka at %s, subscribed to [%s]", KAFKA_BROKER, INPUT_TOPIC)
            return consumer
        except NoBrokersAvailable:
            log.warning(
                "Kafka not ready (attempt %d/%d), retrying in %ds...",
                attempt,
                retries,
                delay,
            )
            time.sleep(delay)
    raise RuntimeError(f"Failed to connect to Kafka after {retries} attempts")


def create_producer() -> KafkaProducer:
    """Create KafkaProducer for publishing decisions to the output topic."""
    return KafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
    )


def save_results(results: list[dict]) -> None:
    """Save prediction results to JSON file."""
    os.makedirs(RESULTS_DIR, exist_ok=True)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_claims": len(results),
        "summary": {
            "approved": sum(1 for r in results if r.get("verdict") == "APPROVED"),
            "denied": sum(1 for r in results if r.get("verdict") == "DENIED"),
            "manual_review": sum(1 for r in results if r.get("verdict") == "MANUAL_REVIEW"),
        },
        "predictions": results,
    }

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    log.info("Saved %d predictions to %s", len(results), RESULTS_FILE)


async def run():
    consumer = create_consumer()
    producer = create_producer()

    results: list[dict] = []
    claim_count = 0
    processed_ids: set[str] = set()

    def shutdown(sig, frame):
        log.info("Shutdown signal received (sig=%d), stopping...", sig)
        _print_summary(results)
        tracker.print_summary()
        tracker.save_report()
        consumer.close()
        producer.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    log.info("Waiting for claims on [%s]...", INPUT_TOPIC)

    for message in consumer:
        claim = message.value
        claim_count += 1
        claim_id = claim.get("claim_id", "unknown")

        if claim_id in processed_ids:
            log.info("[%d] SKIP %s — already processed in this run", claim_count, claim_id)
            continue

        log.info(
            "[%d] Received %s (amount: %s)",
            claim_count,
            claim_id,
            claim.get("claim_amount", "N/A"),
        )

        try:
            decision = await process_claim(claim)
            decision["processed_at"] = datetime.now(timezone.utc).isoformat()
            results.append(decision)

            log.info(
                "━━━ [%d] %s → %s ━━━",
                claim_count,
                claim_id,
                decision.get("verdict", "UNKNOWN"),
            )
        except Exception as e:
            log.error("[%s] Pipeline failed: %s", claim_id, e)
            results.append({
                "claim_id": claim_id,
                "verdict": "MANUAL_REVIEW",
                "reason": f"Pipeline error: {str(e)}",
                "approved_amount": 0,
                "flags": ["pipeline_error"],
                "processed_at": datetime.now(timezone.utc).isoformat(),
            })

        processed_ids.add(claim_id)

        producer.send(OUTPUT_TOPIC, value=results[-1])
        producer.flush()
        log.info("[%s] Published decision to [%s]", claim_id, OUTPUT_TOPIC)

        save_results(results)


def _print_summary(results: list[dict]) -> None:
    log.info(" Session summary: %d claims processed", len(results))
    log.info("   APPROVED:      %d", sum(1 for r in results if r.get("verdict") == "APPROVED"))
    log.info("   DENIED:        %d", sum(1 for r in results if r.get("verdict") == "DENIED"))
    log.info("   MANUAL_REVIEW: %d", sum(1 for r in results if r.get("verdict") == "MANUAL_REVIEW"))
    log.info(" Results saved to: %s", RESULTS_FILE)


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
