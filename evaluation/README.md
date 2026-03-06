# Evaluation

LLM-as-a-Judge evaluation using [DeepEval](https://github.com/confident-ai/deepeval). No ground truth needed — each agent decision is scored against the policy document it was based on.

## Metrics

| Metric | What it checks |
|--------|---------------|
| **Faithfulness** | Is the decision grounded in the policy? No unsupported claims. |
| **Hallucination** | Does the output contradict facts stated in the policy? |

Judge model: `gemini-2.5-flash` (configurable via `JUDGE_MODEL` in `evaluator.py`)

## Setup

Make sure `results/predictions.json` exists (run the agent system first), then:

```bash
# from project root
source .venv/bin/activate
set -a && source .env && set +a

python evaluation/run_evaluation.py
```

## Output

Results are written to `results/`:

- `evaluation_report.json` — per-claim scores, reasons, aggregated summary

```json
{
  "summary_metrics": {
    "faithfulness":  { "avg_score": 0.95, "pass_rate": 0.92 },
    "hallucination": { "avg_score": 0.08, "pass_rate": 0.96 }
  },
  "details": [
    {
      "claim_id": "CLM-001",
      "verdict": "DENIED",
      "faithfulness_score": 1.0,
      "faithfulness_passed": true,
      "hallucination_score": 0.0,
      "hallucination_passed": true
    }
  ]
}
```

## How it works

Each claim becomes one `LLMTestCase`:
- `input` — claim details (patient, amount, diagnosis)
- `actual_output` — agent decision (verdict, reason, flags)
- `context` / `retrieval_context` — the policy document

DeepEval passes this to `GeminiJudge`, which calls the Gemini API to score faithfulness and hallucination against the policy. Results are aggregated per claim and by verdict type.
