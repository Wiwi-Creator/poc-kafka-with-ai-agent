import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger(__name__)

RESULTS_DIR = os.getenv("RESULTS_DIR", "/app/results")
TOKEN_USAGE_FILE = os.path.join(RESULTS_DIR, "token_usage.json")


@dataclass
class TokenRecord:
    agent_name: str
    claim_id: str
    prompt_tokens: int
    candidates_tokens: int
    total_tokens: int
    thoughts_tokens: int = 0


class TokenTracker:
    """Singleton tracker that accumulates token usage across all agent calls."""

    def __init__(self):
        self.records: list[TokenRecord] = []
        self._current_claim_id: str = "unknown"

    def set_current_claim(self, claim_id: str):
        """Set which claim is currently being processed."""
        self._current_claim_id = claim_id

    def create_callback(self, agent_name: str):
        """Create an after_model_callback for a specific agent.

        Returns a callback function that ADK will invoke after each LLM call.
        """
        tracker = self

        def callback(*, callback_context, llm_response):
            usage = llm_response.usage_metadata
            if usage:
                record = TokenRecord(
                    agent_name=agent_name,
                    claim_id=tracker._current_claim_id,
                    prompt_tokens=usage.prompt_token_count or 0,
                    candidates_tokens=usage.candidates_token_count or 0,
                    total_tokens=usage.total_token_count or 0,
                    thoughts_tokens=usage.thoughts_token_count or 0,
                )
                tracker.records.append(record)
                log.debug(
                    "[%s] %s: prompt=%d, output=%d, total=%d",
                    record.claim_id,
                    agent_name,
                    record.prompt_tokens,
                    record.candidates_tokens,
                    record.total_tokens,
                )
            return llm_response

        return callback

    def get_summary(self) -> dict:
        """Generate a summary report of token usage."""
        agent_stats: dict[str, dict] = {}

        for r in self.records:
            if r.agent_name not in agent_stats:
                agent_stats[r.agent_name] = {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "candidates_tokens": 0,
                    "thoughts_tokens": 0,
                    "total_tokens": 0,
                }
            stats = agent_stats[r.agent_name]
            stats["calls"] += 1
            stats["prompt_tokens"] += r.prompt_tokens
            stats["candidates_tokens"] += r.candidates_tokens
            stats["thoughts_tokens"] += r.thoughts_tokens
            stats["total_tokens"] += r.total_tokens

        total_calls = sum(s["calls"] for s in agent_stats.values())
        total_prompt = sum(s["prompt_tokens"] for s in agent_stats.values())
        total_candidates = sum(s["candidates_tokens"] for s in agent_stats.values())
        total_thoughts = sum(s["thoughts_tokens"] for s in agent_stats.values())
        total_all = sum(s["total_tokens"] for s in agent_stats.values())

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "per_agent": agent_stats,
            "totals": {
                "calls": total_calls,
                "prompt_tokens": total_prompt,
                "candidates_tokens": total_candidates,
                "thoughts_tokens": total_thoughts,
                "total_tokens": total_all,
            },
            "per_claim": self._per_claim_breakdown(),
        }

    def _per_claim_breakdown(self) -> dict:
        """Group token usage by claim_id."""
        claims: dict[str, dict] = {}

        for r in self.records:
            if r.claim_id not in claims:
                claims[r.claim_id] = {
                    "calls": 0,
                    "total_tokens": 0,
                    "agents": {},
                }
            claim = claims[r.claim_id]
            claim["calls"] += 1
            claim["total_tokens"] += r.total_tokens
            claim["agents"][r.agent_name] = claim["agents"].get(r.agent_name, 0) + r.total_tokens

        return claims

    def save_report(self):
        """Save token usage report to JSON file."""
        os.makedirs(RESULTS_DIR, exist_ok=True)
        summary = self.get_summary()

        with open(TOKEN_USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        log.info("Token usage report saved to %s", TOKEN_USAGE_FILE)

    def print_summary(self):
        """Print a formatted summary table to log."""
        summary = self.get_summary()
        totals = summary["totals"]
        per_agent = summary["per_agent"]

        log.info("=" * 70)
        log.info(" Token Usage Report")
        log.info("=" * 70)
        log.info(
            " %-22s %6s %10s %10s %10s",
            "Agent", "Calls", "Prompt", "Output", "Total",
        )

        for agent_name, stats in per_agent.items():
            log.info(
                " %-22s %6d %10d %10d %10d",
                agent_name,
                stats["calls"],
                stats["prompt_tokens"],
                stats["candidates_tokens"],
                stats["total_tokens"],
            )

        log.info(
            " %-22s %6d %10d %10d %10d",
            "TOTAL",
            totals["calls"],
            totals["prompt_tokens"],
            totals["candidates_tokens"],
            totals["total_tokens"],
        )
        log.info("=" * 70)


# Global singleton
tracker = TokenTracker()
