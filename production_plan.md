# Production Considerations

## POC vs Production

| Area | POC | Production |
|------|-----|------------|
| Offset commit | manual commit after forwarding | manual commit, only after result is persisted |
| Failure handling | fallback to `MANUAL_REVIEW`, no retry | Dead Letter Topic, retryable, separate from normal results |
| Scale out | single instance | multiple replicas + partitions |
| Result storage | `predictions.json` file | PostgreSQL / BigQuery |
| Policy DB | local JSON file | PostgreSQL / Cloud SQL |
| Claims history | local JSON file | PostgreSQL / Cloud SQL |
| LLM Observability | custom Python script | MLflow / Vertex AI (token usage, latency, tracing) |
| Deployment | Docker Compose (single host) | Kubernetes with HPA auto-scale |

---

## Details

### Offset Commit — Manual

Default `enable_auto_commit=True` advances the offset before processing completes.
A crash between commit and DB write will silently drop the claim.

```python
consumer = KafkaConsumer(..., enable_auto_commit=False)

try:
    decision = await process_claim(claim)
    db.insert(decision)          # persist first
    producer.send("claim-results", decision)
    consumer.commit()            # then tell Kafka we're done
except Exception as e:
    producer.send("claims-dead-letter", {"claim_id": claim_id, "error": str(e)})
    consumer.commit()            # commit on failure too, avoid infinite retry
```

---

### Failure Handling — Dead Letter Topic

Failed claims are currently mixed into results as `MANUAL_REVIEW`. In production,
route them to a separate topic to keep normal results clean and enable retry.

```
ai-agent-service
  ├── success → claim-results          (normal flow)
  └── failure → claims-dead-letter     (retry later or escalate)
```

Dead letter messages include the original claim and error context, so they can be
replayed into `claims-pending` after the root cause is fixed.

---

### Scale Out

Partition count on `claims-pending` determines max parallelism:

| Partition | Assigned to |
|-----------|-------------|
| partition 0 | ai-agent-service instance 1 |
| partition 1 | ai-agent-service instance 2 |
| partition 2 | ai-agent-service instance 3 |

---

### Policy DB & Claims History → PostgreSQL

Local JSON files don't support concurrent reads across multiple instances or live updates.

| | POC | Production |
|---|-----|------------|
| policy_lookup | reads `data/policy_db.json` | `SELECT * FROM policies WHERE policy_id = $1` |
| claim_history | reads `data/claims_history.json` | `SELECT * FROM claims_history WHERE policy_id = $1` |

---

### Docker Compose → Kubernetes

| Service | POC (Docker Compose) | Production (Kubernetes) |
|---------|---------------------|------------------------|
| `consumer-service` | × 1 | replicas: 1 |
| `ai-agent-service` | × 1 | replicas: N, HPA auto-scale |
| Kafka | container | Confluent Cloud / MSK / Strimzi |
| PostgreSQL | — | Cloud SQL / RDS / AlloyDB |


HPA scales `ai-agent-service` based on `claims-pending` consumer lag:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ai-agent-service-hpa
spec:
  scaleTargetRef:
    name: ai-agent-service
  minReplicas: 1
  maxReplicas: 10
  metrics:
    - type: External
      external:
        metric:
          name: kafka_consumer_lag
        target:
          type: AverageValue
          averageValue: "10"
```

---

### LLM Observability

| Signal | POC | Production |
|--------|-----|------------|
| Token usage | logged per agent via `after_model_callback` | persisted to DB, aggregated by model / agent / claim |
| Latency | printed to stdout | tracked per agent call, p50/p95/p99 in dashboards |
| Tracing | none | distributed trace per claim (Extraction → Reviewer → Decider) |
| Cost | estimated from token counts | real-time cost tracking per request |
| Errors / retries | logged to stdout | alerting on error rate, dead-letter spike |

---

## Production Architecture

```
External System / API
      │
      ▼
Kafka: insurance-claims
      │
      ▼
consumer-service (replicas: 1)
      │
      ▼
Kafka: claims-pending
      │
      ▼
ai-agent-service (auto-scale 1~10)
  │   │
  │   └── PostgreSQL
  │         ├── policies         (was policy_db.json)
  │         ├── claims_history   (was claims_history.json)
  │         └── claim_decisions  (was predictions.json)
  │
  ├── Kafka: claim-results
  │         └── downstream services (notifications, reporting, audit)
  │
  └── Kafka: claims-dead-letter
            └── retry pipeline or manual review
```
