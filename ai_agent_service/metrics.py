from prometheus_client import Counter, Gauge, Histogram, start_http_server

METRICS_PORT = 8888

tokens_total = Counter(
    "ai_agent_tokens_total",
    "Total tokens consumed by LLM agents",
    ["agent_name", "token_type"],  # token_type: prompt | completion | thoughts
)

claims_processed_total = Counter(
    "ai_agent_claims_processed_total",
    "Total claims processed, labelled by final verdict",
    ["verdict"],  # APPROVED | DENIED | MANUAL_REVIEW
)

agent_duration_seconds = Histogram(
    "ai_agent_processing_duration_seconds",
    "Seconds spent inside each agent LLM call",
    ["agent_name"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0],
)

pipeline_duration_seconds = Histogram(
    "ai_agent_pipeline_duration_seconds",
    "Total seconds from claim received to decision published",
    buckets=[5.0, 10.0, 20.0, 30.0, 60.0, 90.0, 120.0, 180.0],
)

claims_in_flight = Gauge(
    "ai_agent_claims_in_flight",
    "Number of claims currently being processed by the pipeline",
)


def start_metrics_server() -> None:
    """Start the Prometheus HTTP server (non-blocking)."""
    start_http_server(METRICS_PORT)
