import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone

from deepeval import evaluate
from deepeval.evaluate.configs import AsyncConfig, DisplayConfig
from deepeval.test_case import LLMTestCase

from evaluator import GeminiJudge, build_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Evaluation] %(message)s",
)
log = logging.getLogger(__name__)

_DIR = os.path.dirname(__file__)

PREDICTIONS_FILE = os.getenv(
    "PREDICTIONS_FILE",
    os.path.join(_DIR, "..", "results", "predictions.json"),
)
POLICY_DB_FILE = os.path.join(_DIR, "..", "ai_agent_service", "data", "policy_db.json")
CLAIMS_FILE = os.path.join(_DIR, "..", "producer", "data", "sample_claims.json")
REPORT_JSON = os.path.join(_DIR, "..", "results", "evaluation_report.json")
REPORT_MD = os.path.join(_DIR, "..", "results", "evaluation_report.md")


def _format_input(claim: dict) -> str:
    return (
        f"Claim ID: {claim['claim_id']}\n"
        f"Policy ID: {claim['policy_id']}\n"
        f"Patient: {claim['patient_name']}\n"
        f"Claim Amount: {claim['claim_amount']}\n"
        f"Diagnosis: {claim['diagnosis_text']}"
    )


def _format_output(prediction: dict) -> str:
    return (
        f"Verdict: {prediction.get('verdict')}\n"
        f"Reason: {prediction.get('reason')}\n"
        f"Flags: {prediction.get('flags', [])}\n"
        f"Approved Amount: {prediction.get('approved_amount', 0)}"
    )


def run():
    # ── Load data ─────────────────────────────────────────────────────────
    with open(PREDICTIONS_FILE, encoding="utf-8") as f:
        predictions_data = json.load(f)

    with open(POLICY_DB_FILE, encoding="utf-8") as f:
        policy_db = json.load(f)

    with open(CLAIMS_FILE, encoding="utf-8") as f:
        claims = {c["claim_id"]: c for c in json.load(f)}

    predictions = predictions_data["predictions"]
    log.info("Loaded %d predictions to evaluate", len(predictions))

    # ── Build DeepEval test cases ─────────────────────────────────────────
    claim_ids = []
    test_cases = []

    for prediction in predictions:
        claim_id = prediction["claim_id"]
        claim = claims[claim_id]
        policy = policy_db[claim["policy_id"]]
        policy_str = json.dumps(policy, ensure_ascii=False)

        test_case = LLMTestCase(
            input=_format_input(claim),
            actual_output=_format_output(prediction),
            # context: for HallucinationMetric (facts the output should not contradict)
            context=[policy_str],
            # retrieval_context: for FaithfulnessMetric (source docs the output should be grounded in)
            retrieval_context=[policy_str],
        )
        claim_ids.append(claim_id)
        test_cases.append(test_case)

    # ── Run evaluation ────────────────────────────────────────────────────
    judge = GeminiJudge()
    metrics = build_metrics(judge)

    log.info("Running DeepEval with judge: %s", judge.get_model_name())
    eval_result = evaluate(
        test_cases=test_cases,
        metrics=metrics,
        async_config=AsyncConfig(run_async=True, max_concurrent=2),
        display_config=DisplayConfig(print_results=False),
    )

    # ── Extract per-claim results ─────────────────────────────────────────
    details = []
    for claim_id, test_result in zip(claim_ids, eval_result.test_results):
        row = {"claim_id": claim_id, "verdict": predictions[claim_ids.index(claim_id)].get("verdict")}
        for metric_data in test_result.metrics_data:
            key = metric_data.name.lower().replace(" [geval]", "").replace(" ", "_")
            row[f"{key}_score"] = metric_data.score
            row[f"{key}_reason"] = metric_data.reason
            row[f"{key}_passed"] = metric_data.success
        details.append(row)

    # ── Aggregate metrics ─────────────────────────────────────────────────
    total = len(details)
    metric_names = ["faithfulness", "hallucination"]

    def avg_score(metric: str) -> float:
        scores = [r.get(f"{metric}_score") for r in details if r.get(f"{metric}_score") is not None]
        return round(sum(scores) / len(scores), 4) if scores else 0.0

    def pass_rate(metric: str) -> float:
        passed = [r for r in details if r.get(f"{metric}_passed") is True]
        return round(len(passed) / total, 4) if total > 0 else 0.0

    verdict_breakdown: dict = defaultdict(lambda: {"count": 0, "passed": defaultdict(int)})
    for r in details:
        v = r["verdict"]
        verdict_breakdown[v]["count"] += 1
        for m in metric_names:
            if r.get(f"{m}_passed"):
                verdict_breakdown[v]["passed"][m] += 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "judge_model": judge.get_model_name(),
        "total_evaluated": total,
        "summary_metrics": {
            m: {"avg_score": avg_score(m), "pass_rate": pass_rate(m)}
            for m in metric_names
        },
        "verdict_breakdown": {
            v: {"count": stats["count"], "passed": dict(stats["passed"])}
            for v, stats in verdict_breakdown.items()
        },
        "details": details,
    }

    # ── Save JSON ─────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(REPORT_JSON), exist_ok=True)
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # ── Generate Markdown ─────────────────────────────────────────────────
    _write_markdown(report, details, metric_names)

    # ── Print summary ─────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info(" Evaluation Report — %d claims", total)
    log.info("=" * 60)
    for m in metric_names:
        s = report["summary_metrics"][m]
        log.info(" %-32s score=%.2f  pass=%.1f%%", m, s["avg_score"], s["pass_rate"] * 100)
    log.info("=" * 60)
    log.info(" JSON → %s", REPORT_JSON)
    log.info(" MD   → %s", REPORT_MD)


def _write_markdown(report: dict, details: list, metric_names: list) -> None:
    total = report["total_evaluated"]
    lines = []

    lines += [
        "# LLM-as-a-Judge Evaluation Report",
        "",
        f"> Generated: {report['generated_at']}  ",
        f"> Judge model: {report['judge_model']}  ",
        f"> Claims evaluated: {total}  ",
        f"> Framework: [DeepEval](https://github.com/confident-ai/deepeval)",
        "",
        "---",
        "",
        "## Summary Metrics",
        "",
        "| Metric | Avg Score | Pass Rate |",
        "|--------|-----------|-----------|",
    ]
    for m in metric_names:
        s = report["summary_metrics"][m]
        label = m.replace("_", " ").title()
        lines.append(f"| {label} | {s['avg_score']:.2f} | {s['pass_rate']*100:.1f}% |")
    lines.append("")

    lines += [
        "## By Verdict",
        "",
        "| Verdict | Count | Faithfulness | Hallucination |",
        "|---------|-------|--------------|---------------|",
    ]
    for v, stats in report["verdict_breakdown"].items():
        p = stats["passed"]
        n = stats["count"]
        lines.append(
            f"| {v} | {n} "
            f"| {p.get('faithfulness', 0)}/{n} "
            f"| {p.get('hallucination', 0)}/{n} |"
        )
    lines.append("")

    lines += [
        "## Per-Claim Results",
        "",
        "| Claim | Verdict | Faithful | Hallucination |",
        "|-------|---------|----------|---------------|",
    ]
    for r in details:
        def fmt(m):
            passed = r.get(f"{m}_passed")
            score = r.get(f"{m}_score")
            icon = "✓" if passed else "✗"
            return f"{icon} {score:.2f}" if score is not None else "—"

        lines.append(
            f"| {r['claim_id']} | {r['verdict']} "
            f"| {fmt('faithfulness')} "
            f"| {fmt('hallucination')} |"
        )
    lines.append("")

    lines += ["## Metric Reasoning per Claim", ""]
    for r in details:
        lines += [f"### {r['claim_id']} — `{r['verdict']}`", ""]
        for m in metric_names:
            label = m.replace("_", " ").title()
            reason = r.get(f"{m}_reason", "—")
            passed = r.get(f"{m}_passed")
            icon = "✓" if passed else "✗"
            lines += [f"**{icon} {label}**: {reason}", ""]

    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    run()
