import json
import logging
import time

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from agents.extraction import extraction_agent
from agents.reviewer import reviewer_agent
from agents.decider import decider_agent
from metrics import agent_duration_seconds, pipeline_duration_seconds
from token_tracker import tracker

log = logging.getLogger(__name__)

APP_NAME = "insurance-claim-processor"
session_service = InMemorySessionService()


async def _run_agent(runner: Runner, user_id: str, session_id: str, message: str) -> str:
    """Run a single agent and return its text response."""
    # Create a fresh session for this agent invocation
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )

    content = Content(parts=[Part(text=message)], role="user")
    final_text = ""

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    final_text = part.text

    return final_text


async def process_claim(claim: dict) -> dict:
    """Process a single insurance claim through the 3-agent pipeline."""
    claim_id = claim["claim_id"]
    user_id = f"claim-{claim_id}"

    start_time = time.time()
    log.info("[%s] Starting agent pipeline", claim_id)
    tracker.set_current_claim(claim_id)

    # ── Agent 1: Extraction ──────────────────────────────────────────────
    extraction_runner = Runner(
        app_name=APP_NAME,
        agent=extraction_agent,
        session_service=session_service,
    )
    extraction_session_id = f"{claim_id}-extraction"
    extraction_prompt = (
        f"Extract medical features from this diagnosis:\n\n"
        f"{claim['diagnosis_text']}"
    )

    log.info("[%s] Agent 1 (Extraction): processing...", claim_id)
    _t0 = time.time()
    extraction_raw = await _run_agent(
        extraction_runner, user_id, extraction_session_id, extraction_prompt
    )
    agent_duration_seconds.labels(agent_name="extraction").observe(time.time() - _t0)
    log.info("[%s] Agent 1 (Extraction): done → %s", claim_id, extraction_raw[:200])

    # ── Agent 2: Policy Reviewer (with Tool Use) ─────────────────────────
    reviewer_runner = Runner(
        app_name=APP_NAME,
        agent=reviewer_agent,
        session_service=session_service,
    )
    reviewer_session_id = f"{claim_id}-reviewer"
    reviewer_prompt = (
        f"Verify this insurance claim against policy rules and claim history.\n\n"
        f"Claim ID: {claim['claim_id']}\n"
        f"Policy ID: {claim['policy_id']}\n"
        f"Claim Amount: {claim['claim_amount']}\n"
        f"Extraction Result:\n{extraction_raw}"
    )

    log.info("[%s] Agent 2 (Reviewer): processing with Tool Use...", claim_id)
    _t0 = time.time()
    review_raw = await _run_agent(
        reviewer_runner, user_id, reviewer_session_id, reviewer_prompt
    )
    agent_duration_seconds.labels(agent_name="reviewer").observe(time.time() - _t0)
    log.info("[%s] Agent 2 (Reviewer): done → %s", claim_id, review_raw[:200])

    # ── Agent 3: Final Decider ───────────────────────────────────────────
    decider_runner = Runner(
        app_name=APP_NAME,
        agent=decider_agent,
        session_service=session_service,
    )
    decider_session_id = f"{claim_id}-decider"
    decider_prompt = (
        f"Make a final decision on this insurance claim.\n\n"
        f"Claim ID: {claim['claim_id']}\n"
        f"Claim Amount: {claim['claim_amount']}\n"
        f"Patient: {claim['patient_name']}\n\n"
        f"Extraction Result:\n{extraction_raw}\n\n"
        f"Policy Review Result:\n{review_raw}"
    )

    log.info("[%s] Agent 3 (Decider): processing...", claim_id)
    _t0 = time.time()
    decision_raw = await _run_agent(
        decider_runner, user_id, decider_session_id, decider_prompt
    )
    agent_duration_seconds.labels(agent_name="decider").observe(time.time() - _t0)
    log.info("[%s] Agent 3 (Decider): done → %s", claim_id, decision_raw[:200])

    elapsed = time.time() - start_time
    pipeline_duration_seconds.observe(elapsed)

    # ── Parse decision ───────────────────────────────────────────────────
    try:
        decision = json.loads(decision_raw)
    except json.JSONDecodeError:
        log.warning("[%s] Failed to parse decision JSON, wrapping as MANUAL_REVIEW", claim_id)
        decision = {
            "claim_id": claim_id,
            "verdict": "MANUAL_REVIEW",
            "reason": f"Agent output could not be parsed: {decision_raw[:500]}",
            "approved_amount": 0,
            "flags": ["parse_error"],
        }

    decision["claim_id"] = claim_id
    decision["processing_time_sec"] = round(elapsed, 2)

    log.info("[%s] Pipeline complete in %.1fs → %s", claim_id, elapsed, decision.get("verdict", "UNKNOWN"))
    return decision
