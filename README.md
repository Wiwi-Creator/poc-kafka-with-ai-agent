# Multi-Agent Insurance Claim Processor

A proof-of-concept multi-agent system that processes insurance claims through a 3-stage AI pipeline, powered by **Google ADK** and streamed via **Apache Kafka**.

## Architecture

```mermaid
graph LR
    P[producer/main.py<br/>Local Script] -- "1. Send JSON" --> K

    subgraph "Docker Compose"
        K((Kafka Broker<br/>+ Zookeeper))
        KUI[Kafka UI<br/>:8080]

        CS[consumer-service] -- "2. Poll" --> K
        CS -- "3. Forward" --> KP[Kafka: claims-pending]

        subgraph "ai-agent-service"
            KP -- "4. Poll" --> O[Orchestrator]
            O --> E[Agent 1<br/>Extraction]
            O --> R[Agent 2<br/>Policy Reviewer]
            O --> D[Agent 3<br/>Final Decider]
            R -- "Tool Use" --> T1[check_policy_rules]
            R -- "Tool Use" --> T2[get_claim_history]
        end
    end

    subgraph "Gemini API"
        E & R & D -- "API Call" --> G[gemini-2.5-flash]
    end

    O -- "5. Publish" --> KR[Kafka: claim-results]
    O -- "6. Save" --> RF[results/predictions.json]
```

## Architecture Evolution

### v1 — Single Service (original)

```
producer → insurance-claims → agent-system (poll + LLM in same loop)
                                    └── predictions.json
```

**Problem**: LLM processing blocks the consumer loop. Each claim takes ~30-60s,
causing Kafka to trigger rebalance (`CommitFailedError`) after several claims.

### v2 — Split Services (current)

```
producer → insurance-claims → consumer-service (fast, only forwards)
                                    └── claims-pending → ai-agent-service (LLM)
                                                              └── claim-results
                                                              └── predictions.json
```

**Improvement**: `consumer-service` polls and commits in milliseconds. `ai-agent-service`
can take as long as needed per claim without affecting Kafka heartbeat.

| | v1 | v2 |
|---|---|---|
| Services | 1 | 2 |
| Topics | 2 | 3 |
| Kafka timeout risk | Yes | No |
| Responsibility | Mixed | Separated |

---

## Agent Pipeline

Each claim flows through 3 agents sequentially:

```
Diagnosis Text --> [Extraction Agent] --> [Policy Reviewer] --> [Final Decider] --> Verdict
                    Gemini 2.5 Flash     Gemini 2.5 Flash     Gemini 2.5 Flash
                                           + Tool Use
```

| Agent | Role | Tools |
|-------|------|-------|
| Agent 1: Extraction | Extracts surgery type, disease, severity, hospitalization days from free-text diagnosis | None |
| Agent 2: Policy Reviewer | Verifies claim against policy rules and claim history | `check_policy_rules`, `get_claim_history` |
| Agent 3: Final Decider | Issues final verdict based on extraction + review | None |

**Verdicts:** `APPROVED` / `DENIED` / `MANUAL_REVIEW`

## Project Structure

```
poc-kafka-with-ai-agent/
├── docker-compose.yml
├── requirements.txt            # Top-level venv (local dev)
├── .env                        # GOOGLE_API_KEY (gitignored)
├── .env.example
│
├── producer/
│   ├── main.py                 # CLI script: send claims to Kafka
│   └── data/
│       └── sample_claims.json  # 50 simulated insurance claims
│
├── consumer_service/
│   ├── main.py                 # Poll insurance-claims, forward to claims-pending
│   └── Dockerfile
│
├── ai_agent_service/
│   ├── main.py                 # Poll claims-pending, run LLM pipeline
│   ├── orchestrator.py         # Sequential 3-agent pipeline
│   ├── token_tracker.py        # Token usage tracking via after_model_callback
│   ├── test_local.py           # Local test without Kafka
│   ├── agents/
│   │   ├── extraction.py       # Agent 1
│   │   ├── reviewer.py         # Agent 2 (Tool Use)
│   │   └── decider.py          # Agent 3
│   ├── tools/
│   │   ├── policy_lookup.py    # check_policy_rules()
│   │   └── claim_history.py    # get_claim_history()
│   └── data/
│       ├── policy_db.json      # 9 simulated insurance policies
│       └── claims_history.json # Historical claims per policy
│
├── evaluation/
│   ├── evaluator.py            # GeminiJudge + DeepEval metrics
│   ├── run_evaluation.py       # Main evaluation runner
│   └── README.md               # How to run evaluation
│
└── results/                    # Output (Docker volume mount)
    ├── predictions.json
    ├── token_usage.json
    └── evaluation_report.json
```

## Quick Start

### Prerequisites

- Docker Desktop (running)
- Gemini API key

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env and set your GOOGLE_API_KEY
```

### 2. Install local dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Start infrastructure + agent system

```bash
docker compose up -d
```

This starts Kafka + Zookeeper, Kafka UI (`:8080`), `consumer-service`, and `ai-agent-service`.

### 4. Send claims

```bash
# Send all 50 claims (3s interval)
python producer/main.py

# Or control count and speed
python producer/main.py --count 5 --interval 1
```

### 5. Monitor

```bash
docker logs -f consumer-service    # forwarding logs
docker logs -f ai-agent-service    # LLM processing logs

# Results file (updated after each claim)
cat results/predictions.json
```

**Kafka UI**: http://localhost:8080

| Page | What you can see |
|------|-----------------|
| `insurance-claims` topic | Raw claims from producer |
| `claims-pending` topic | Forwarded by consumer-service |
| `claim-results` topic | Agent decisions |
| Consumer groups | `consumer-service-group`, `ai-agent-service-group` |

### 6. Shut down

```bash
docker compose down
```

## Local Test (without Docker)

```bash
source .venv/bin/activate
set -a && source .env && set +a
python ai_agent_service/test_local.py
```

## Re-run

To reprocess all claims from scratch, reset Kafka offsets by restarting:

```bash
docker compose down && docker compose up -d
python producer/main.py
```
