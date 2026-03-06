import json
import os

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "policy_db.json")


def check_policy_rules(policy_id: str, surgery_type: str) -> dict:
    """Query the policy database for coverage rules and claim limits.

    This tool looks up a policy by ID and checks whether the given surgery type
    is covered. It returns the policy details including coverage status, limits,
    exclusions, and current usage.

    Args:
        policy_id: The policy ID to look up (e.g., "POL-A100").
        surgery_type: The type of surgery to check coverage for (e.g., "appendectomy").

    Returns:
        A dict containing:
        - found: whether the policy exists
        - policy_id: the queried policy ID
        - status: policy status (active/expired)
        - plan: plan name
        - surgery_coverage: whether the plan covers surgery
        - max_per_claim: maximum amount per single claim
        - annual_limit: annual total limit
        - annual_used: amount already used this year
        - annual_remaining: remaining annual budget
        - exclusions: list of excluded procedures
        - is_excluded: whether the surgery_type matches an exclusion
        - matched_exclusion: which exclusion rule matched (if any)
    """
    with open(_DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)

    if policy_id not in db:
        return {
            "found": False,
            "policy_id": policy_id,
            "error": f"Policy {policy_id} not found in database.",
        }

    policy = db[policy_id]
    surgery_lower = surgery_type.lower()

    # Check if surgery matches any exclusion keyword
    matched_exclusion = None
    for exclusion in policy["exclusions"]:
        if exclusion.lower() in surgery_lower or surgery_lower in exclusion.lower():
            matched_exclusion = exclusion
            break

    annual_remaining = policy["annual_limit"] - policy["annual_used"]

    return {
        "found": True,
        "policy_id": policy_id,
        "holder": policy["holder"],
        "status": policy["status"],
        "plan": policy["plan"],
        "surgery_coverage": policy["surgery_coverage"],
        "max_per_claim": policy["max_per_claim"],
        "annual_limit": policy["annual_limit"],
        "annual_used": policy["annual_used"],
        "annual_remaining": annual_remaining,
        "exclusions": policy["exclusions"],
        "is_excluded": matched_exclusion is not None,
        "matched_exclusion": matched_exclusion,
        "effective_date": policy["effective_date"],
        "expiry_date": policy["expiry_date"],
    }
