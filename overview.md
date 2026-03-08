# Architecture & Design: Multi-Agent Insurance Claim System

> **Tech Stack:** Google ADK + Kafka + Docker Compose
> **Runtime:** Local (Docker), Cloud-LLM (Gemini API)

---

## 1. System Architecture

### 1.1 Kafka Message Flow

```
producer/main.py
    │
    ▼
Kafka: insurance-claims
    │
    ▼
consumer-service          ← fast forward only, no LLM
    │
    ▼
Kafka: claims-pending
    │
    ▼
ai-agent-service          ← 3-agent LLM pipeline
    │
    ▼
Kafka: claim-results
```

| Topic | Producer | Consumer | Purpose |
|-------|----------|----------|---------|
| `insurance-claims` | `producer/main.py` | `consumer-service` | Raw claim ingestion |
| `claims-pending` | `consumer-service` | `ai-agent-service` | Decouples fast poll from slow LLM |
| `claim-results` | `ai-agent-service` | downstream services | Final decisions |

- **Serialization**: JSON (UTF-8)
- **Offset reset**: `earliest` — consumer reads from the beginning
- **consumer-service**: `enable_auto_commit=False`, commits after forwarding
- **ai-agent-service**: `max_poll_interval_ms=600000` (10 min) to accommodate LLM processing time

---

### 1.2 Architecture Evolution

### v1 — Single Service (original)

**Problem**: The single service ran poll → LLM → commit in the same loop. Kafka's default `max_poll_records=500` means one `poll()` call can fetch many messages at once. The `for` loop then processes all of them without calling `poll()` again. If the producer sent 8 claims before the consumer started, the first poll fetches all 8. Each claim takes ~40s — so 8 × 40s = 320s, exceeding the default `max_poll_interval_ms=300s`. Kafka assumes the consumer is dead and triggers a rebalance (`CommitFailedError`).

```mermaid
sequenceDiagram
    participant K as Kafka: insurance-claims
    participant A as agent-system (single service)
    participant L as Gemini API

    Note over K,A: max_poll_interval_ms = 300s (default), max_poll_records = 500

    A->>K: poll() → fetches CLM-001 ~ CLM-008 at once
    A->>L: LLM pipeline (CLM-001, ~40s)
    L-->>A: decision
    A->>K: commit()

    A->>L: LLM pipeline (CLM-002, ~40s)
    L-->>A: decision
    A->>K: commit()

    Note over K,A: No poll() called since start. 8 × 40s = 320s > 300s

    A->>L: LLM pipeline (CLM-003...)
    A->>K: commit() Error : CommitFailedError
    Note over K,A: Consumer kicked from group, rebalance triggered
```

### v2 — Split Services (current)

**Improvement**: Splitting into two services separates fast ingestion from slow LLM processing. `consumer-service` only polls and forwards — completes in milliseconds, never at risk of timeout. `ai-agent-service` handles one claim at a time (`max_poll_records=1`) with its own independent timer (`max_poll_interval_ms=600s`), well above the ~40s needed per claim. The split also enables independent scaling: partition count on `claims-pending` determines how many `ai-agent-service` instances can run in parallel.

```mermaid
sequenceDiagram
    participant K1 as Kafka: insurance-claims
    participant CS as consumer-service
    participant K2 as Kafka: claims-pending
    participant AI as ai-agent-service
    participant L as Gemini API

    Note over CS: poll + forward only, completes in milliseconds

    CS->>K1: poll() → CLM-001
    CS->>K2: forward
    CS->>K1: commit()

    CS->>K1: poll() → CLM-002
    CS->>K2: forward
    CS->>K1: commit()

    Note over AI: max_poll_interval_ms = 600s, independent timer

    AI->>K2: poll() → CLM-001
    AI->>L: LLM pipeline
    L-->>AI: decision
    AI->>K2: commit()

    AI->>K2: poll() → CLM-002
    AI->>L: LLM pipeline
    L-->>AI: decision
    AI->>K2: commit()
```

| | v1 | v2 |
|---|---|---|
| Services | 1 | 2 |
| Topics | 2 | 3 |
| `max_poll_records` | 500 (default) | 1 (ai-agent-service) |
| Kafka timeout risk | Yes | No |
| Responsibility | Mixed | Separated |
| Scale | Only together | Independently |

---

### 1.3 AI Agent Workflow

```mermaid
sequenceDiagram
    participant P as Producer
    participant K as Kafka: insurance-claims
    participant C as Consumer / Orchestrator
    participant A1 as Agent 1: Extraction
    participant A2 as Agent 2: Reviewer
    participant Tool as Tools (policy_lookup, claim_history)
    participant A3 as Agent 3: Decider
    participant KR as Kafka: claim-results

    P ->> K: Publish claim JSON
    C ->> K: Poll message
    K -->> C: claim JSON

    C ->> A1: diagnosis_text
    Note over A1: Extract surgery, disease,<br/>severity, hospitalization days
    A1 -->> C: structured features (JSON)

    C ->> A2: features + policy_id + claim_amount
    A2 ->> Tool: check_policy_rules(policy_id, surgery_type)
    Tool -->> A2: policy coverage & limits
    A2 ->> Tool: get_claim_history(policy_id)
    Tool -->> A2: past claims for this policy
    Note over A2: Compare claim vs policy rules
    A2 -->> C: verification result (JSON)

    C ->> A3: features + verification result
    Note over A3: Synthesize final verdict + reason
    A3 -->> C: APPROVED / DENIED / MANUAL_REVIEW

    C ->> KR: Publish decision JSON
```

---

## 2. Tech Stack

| Component       | Technology              | Purpose                             |
|-----------------|-------------------------|-------------------------------------|
| Agent Framework | `google-adk` (v1.26+)  | Multi-agent orchestration, Tool Use |
| LLM             | Gemini 2.5 Flash        | NLU, reasoning, decision            |
| Message Queue   | Apache Kafka            | Decouple ingestion from processing  |
| Container       | Docker Compose          | One-command local deployment        |
| Language        | Python 3.11             | All application code                |
| Auth            | `GOOGLE_API_KEY` env var | No GCP project needed              |

---

## 3. Agent Design

### Agent 1: Extraction

Extracts structured medical features from free-text diagnosis.

```python
class ExtractionResult(BaseModel):
    surgery_type: str
    disease: str
    hospitalization_days: int
    severity: Literal["low", "medium", "high"]
```

### Agent 2: Policy Reviewer (Tool Use)

Verifies claim against policy rules and claim history by calling two tools. ADK handles the function calling loop automatically:

1. Gemini sees the tool declarations
2. Gemini decides to call `check_policy_rules` and `get_claim_history`
3. ADK executes the Python functions locally
4. ADK sends results back to Gemini
5. Gemini generates the final review

```python
class ReviewResult(BaseModel):
    policy_found: bool
    policy_status: str          # active / expired
    is_covered: bool
    is_excluded: bool
    matched_exclusion: str | None
    max_per_claim: int
    claim_amount: int
    amount_within_limit: bool
    annual_remaining: int
    verification_summary: str
```

### Agent 3: Final Decider

Synthesizes extraction + review into a verdict.

```python
class Decision(BaseModel):
    claim_id: str
    verdict: Literal["APPROVED", "DENIED", "MANUAL_REVIEW"]
    reason: str
    approved_amount: float
    flags: list[str]  # e.g. ["over_limit", "excluded_surgery"]
```

**Decision rules:**
- `APPROVED`: policy active + surgery covered + not excluded + within limits
- `DENIED`: expired policy / excluded surgery / no coverage / over limit
- `MANUAL_REVIEW`: edge cases or conflicting signals

---

## 4. Sample Data

### Insurance Claims (`producer/data/sample_claims.json`)

50 claims across 10 patients and 9 policies:

| Claim ID | Patient | Surgery | Amount | Policy | Expected Scenario |
|----------|---------|---------|--------|--------|-------------------|
| CLM-001 | Wang Xiao-Ming | Laparoscopic Appendectomy | 50,000 | POL-A100 | Over per-claim limit (30k) |
| CLM-002 | Lin Mei-Ling | Laparoscopic Cholecystectomy | 25,000 | POL-B200 | Normal approval |
| CLM-003 | Chen Da-Wei | Rhinoplasty | 80,000 | POL-C300 | Cosmetic surgery exclusion |
| CLM-004 | Zhang Li-Hua | ACL Reconstruction | 120,000 | POL-D400 | Expired policy |
| CLM-005 | Huang Yu-Ting | Emergency PCI (STEMI) | 350,000 | POL-E500 | High severity, premium plan |
| CLM-006 | Wu Jia-Hui | Annual Health Screening | 15,000 | POL-F600 | Preventive checkup exclusion |
| CLM-007 | Liu Zhi-Qiang | Microdiscectomy (L4-L5) | 45,000 | POL-G700 | Normal approval |
| CLM-008 | Xu Shu-Fen | ORIF (distal radius fracture) | 35,000 | POL-H800 | Normal approval |
| CLM-009 | Yang Jing-Wen | Bilateral Cataract Surgery | 28,000 | POL-I900 | Elective surgery exclusion |
| CLM-010 | Wang Xiao-Ming | Incisional Hernia Repair | 40,000 | POL-A100 | Same patient, over limit |
| CLM-011 ~ CLM-050 | (same 10 patients) | Various | Various | Various | Extended scenarios |

### Insurance Policies (`ai_agent_service/data/policy_db.json`)

9 policies:

| Policy | Holder | Plan | Per-Claim Limit | Annual Limit | Status | Key Exclusions |
|--------|--------|------|----------------|--------------|--------|----------------|
| POL-A100 | Wang Xiao-Ming | Basic Medical | 30,000 | 200,000 | active | cosmetic surgery, preventive checkup |
| POL-B200 | Lin Mei-Ling | Standard Medical | 50,000 | 300,000 | active | cosmetic surgery, preventive checkup, dental |
| POL-C300 | Chen Da-Wei | Basic Medical | 40,000 | 200,000 | active | cosmetic surgery, preventive checkup |
| POL-D400 | Zhang Li-Hua | Basic Medical | 60,000 | 250,000 | **expired** | cosmetic surgery, preventive checkup |
| POL-E500 | Huang Yu-Ting | Premium Medical | 500,000 | 1,000,000 | active | cosmetic surgery |
| POL-F600 | Wu Jia-Hui | Standard Medical | 50,000 | 300,000 | active | cosmetic surgery, preventive checkup, dental |
| POL-G700 | Liu Zhi-Qiang | Standard Medical | 50,000 | 300,000 | active | cosmetic surgery, preventive checkup |
| POL-H800 | Xu Shu-Fen | Standard Medical | 50,000 | 300,000 | active | cosmetic surgery, preventive checkup |
| POL-I900 | Yang Jing-Wen | Basic Medical | 20,000 | 150,000 | active | cosmetic surgery, preventive checkup, elective surgery |

> POL-I900 has `surgery_coverage: false` — all surgical claims will be denied regardless of amount.

### Historical Claims (`ai_agent_service/data/claims_history.json`)

Pre-seeded past claims per policy, used by Agent 2 to calculate annual budget consumed:

| Policy | Past Claims | Notable |
|--------|-------------|---------|
| POL-A100 | 0 | — |
| POL-B200 | 1 | knee arthroscopy, APPROVED |
| POL-C300 | 0 | — |
| POL-D400 | 1 | hernia repair, APPROVED |
| POL-E500 | 1 | cardiac catheterization, APPROVED |
| POL-F600 | 0 | — |
| POL-G700 | 2 | gallbladder removal + colonoscopy, both APPROVED |
| POL-H800 | 3 | spinal fusion APPROVED, hip replacement APPROVED, cosmetic surgery DENIED |
| POL-I900 | 0 | — |

---

## 5. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent chaining | Sequential via Orchestrator | Full control over data flow between agents, easier debugging |
| Tool Use | Python functions passed to ADK | ADK auto-handles function calling loop; no manual parsing needed |
| Session management | `InMemorySessionService`, fresh session per agent call | Agents are single-shot; no conversation history needed |
| Output schema | Pydantic models | Enforces structured JSON output from the LLM |
| LLM model | Gemini 2.5 Flash | Fast inference, supports function calling, cost-effective |
| Policy/History data | Local JSON files (no cache) | Simulates DB point-query; cache removed for data freshness |

---

## 6. Token Usage Tracking

Token consumption is tracked via ADK's `after_model_callback` on each agent:

```python
extraction_agent = Agent(
    ...
    after_model_callback=tracker.create_callback("extraction_agent"),
)

def callback(*, callback_context, llm_response):
    usage = llm_response.usage_metadata
    # Records: prompt_tokens, candidates_tokens, thoughts_tokens, total_tokens
```