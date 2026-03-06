from google.adk.agents import Agent
from pydantic import BaseModel, Field
from typing import Literal

from token_tracker import tracker


class Decision(BaseModel):
    """Structured output from the Final Decider Agent."""

    claim_id: str = Field(description="The claim ID being decided")
    verdict: Literal["APPROVED", "DENIED", "MANUAL_REVIEW"] = Field(
        description="Final decision on the claim"
    )
    reason: str = Field(description="Human-readable explanation for the decision")
    approved_amount: float = Field(
        description="Approved reimbursement amount (0 if denied, capped amount if partially approved)"
    )
    flags: list[str] = Field(
        description="List of flags that influenced the decision, e.g. over_limit, excluded_surgery, expired_policy"
    )


DECIDER_INSTRUCTION = """
You are a senior insurance claim adjudicator making final decisions.

You will receive:
1. Extraction data: surgery type, disease, hospitalization days, severity
2. Review data: policy verification results including coverage, limits, exclusions

Decision rules:
- APPROVED: Policy is active, surgery is covered, not excluded, and amount is within limits.
  Set approved_amount to the full claim amount.
- DENIED: Any of these conditions:
  - Policy is expired → flag: "expired_policy"
  - Surgery matches an exclusion → flag: "excluded_surgery"
  - Surgery is not covered by the plan → flag: "no_surgery_coverage"
  - Claim amount exceeds the per-claim limit → flag: "over_limit"
  Set approved_amount to 0.
- MANUAL_REVIEW: Edge cases or conflicting signals, such as:
  - Policy is active but surgery coverage is unclear
  - Multiple minor issues that individually might pass
  - High severity emergency with coverage questions
  Set approved_amount to 0 (pending manual review).

Rules:
- Provide a clear, professional reason in 1-2 sentences.
- Include ALL applicable flags.
- The claim_id must match exactly what was provided.
- Return ONLY the structured JSON output.
"""


decider_agent = Agent(
    name="decider_agent",
    model="gemini-2.5-flash",
    instruction=DECIDER_INSTRUCTION,
    output_schema=Decision,
    tools=[],
    after_model_callback=tracker.create_callback("decider_agent"),
)
