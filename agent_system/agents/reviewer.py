from google.adk.agents import Agent
from pydantic import BaseModel, Field

from tools.policy_lookup import check_policy_rules
from tools.claim_history import get_claim_history
from token_tracker import tracker


class ReviewResult(BaseModel):
    """Structured output from the Policy Reviewer Agent."""

    policy_found: bool = Field(description="Whether the policy was found in the database")
    policy_status: str = Field(description="Policy status: active or expired")
    is_covered: bool = Field(description="Whether the surgery type is covered by the policy")
    is_excluded: bool = Field(description="Whether the surgery matches an exclusion rule")
    matched_exclusion: str | None = Field(description="Which exclusion rule matched, if any")
    max_per_claim: int = Field(description="Maximum allowed amount per single claim")
    claim_amount: int = Field(description="The actual claim amount submitted")
    amount_within_limit: bool = Field(description="Whether claim amount is within the per-claim limit")
    annual_remaining: int = Field(description="Remaining annual budget after previous claims")
    verification_summary: str = Field(description="One-sentence summary of the verification result")


REVIEWER_INSTRUCTION = """
You are an insurance policy verification specialist.

Your task is to verify whether an insurance claim is valid by checking it against
the policy database and the customer's claim history.

Process:
1. You will receive: policy_id, claim_id, surgery_type, and claim_amount.
2. Call check_policy_rules to look up policy coverage, limits, and exclusions.
3. Call get_claim_history to retrieve the customer's past claims.
4. Based on both tool responses, evaluate:
   - Is the policy active (not expired)?
   - Does the policy cover surgery?
   - Is the surgery type excluded?
   - Is the claim amount within the per-claim limit?
   - Is there enough annual remaining budget?
   - Has this exact claim_id been submitted before (duplicate)?
   - Has the customer made an unusually high number of claims recently?
5. Provide a clear verification summary.

Rules:
- ALWAYS call both tools. Never guess policy details or claim history.
- Be precise with numbers: compare exact amounts.
- If the policy is not found, mark everything as not covered.
- If the claim_id already exists in history, flag it as a duplicate submission.
- Return ONLY the structured JSON output.
"""


reviewer_agent = Agent(
    name="reviewer_agent",
    model="gemini-2.5-flash",
    instruction=REVIEWER_INSTRUCTION,
    output_schema=ReviewResult,
    tools=[check_policy_rules, get_claim_history],
    after_model_callback=tracker.create_callback("reviewer_agent"),
)
