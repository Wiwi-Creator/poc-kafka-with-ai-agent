# Multi-Agent Insurance Claim Processor

A proof-of-concept multi-agent system that processes insurance claims through a 3-stage AI pipeline, powered by **Google ADK** and streamed via **Apache Kafka**.

## Architecture

```mermaid
graph LR
    P[producer/main.py<br/>Local Script] -- "1. Send JSON" --> K

    subgraph "Docker Compose"
        K((Kafka Broker<br/>+ Zookeeper))

        subgraph "AI Agent System Container"
            C[Kafka Consumer] -- "2. Poll" --> K
            C -- "3. Trigger" --> O[Orchestrator]
            O --> E[ADK Agent 1<br/>Extraction]
            O --> R[ADK Agent 2<br/>Policy Reviewer]
            O --> D[ADK Agent 3<br/>Final Decider]
            R -- "Tool Use" --> T1[check_policy_rules<br/>policy_db.json]
            R -- "Tool Use" --> T2[get_claim_history<br/>claims_history.json]
        end

        KUI[Kafka UI<br/>:8080]
    end

    subgraph "Gemini API"
        E -- "API Call" --> G[gemini-2.5-flash]
        R -- "API Call" --> G
        D -- "API Call" --> G
    end

    O -- "4. Write Result" --> KR[Kafka: claim-results]
    O -- "5. Save" --> RF[results/predictions.json]
```

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
├── agent_system/
│   ├── Dockerfile
│   ├── main.py                 # Kafka consumer + result persistence
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

This starts Kafka + Zookeeper, Kafka UI (`:8080`), and the Agent System.

### 4. Send claims

```bash
# Send all 50 claims (3s interval)
python producer/main.py

# Or control count and speed
python producer/main.py --count 5 --interval 1
```

### 5. Monitor

```bash
# Agent system logs
docker logs -f agent-system

# Results file (updated after each claim)
cat results/predictions.json
```

**Kafka UI**: http://localhost:8080

| Page | What you can see |
|------|-----------------|
| `insurance-claims` topic | Raw claim JSON as they arrive |
| `claim-results` topic | Agent decisions |
| Consumer groups | `agent-system-group` lag |

### 6. Shut down

```bash
docker compose down
```

## Local Test (without Docker)

```bash
source .venv/bin/activate
set -a && source .env && set +a
python agent_system/test_local.py
```

## Re-run

To reprocess all claims from scratch, reset Kafka offsets by restarting:

```bash
docker compose down && docker compose up -d
python producer/main.py
```
