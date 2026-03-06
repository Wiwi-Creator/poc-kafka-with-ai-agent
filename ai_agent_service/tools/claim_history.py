import json
import os

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "claims_history.json")


def get_claim_history(policy_id: str) -> dict:
    """Retrieve historical claims for a given policy.

    This tool looks up all past claims submitted under a policy ID.
    Use it to detect duplicate submissions and assess claim frequency.

    Args:
        policy_id: The policy ID to look up (e.g., "POL-A100").

    Returns:
        A dict containing:
        - found: whether the policy exists in the history database
        - policy_id: the queried policy ID
        - total_claims: total number of past claims
        - approved_count: number of approved claims
        - denied_count: number of denied claims
        - total_approved_amount: sum of all approved amounts
        - claims: list of past claim records (claim_id, surgery_type,
                  claim_amount, approved_amount, verdict, submitted_at)
    """
    with open(_DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)

    if policy_id not in db:
        return {
            "found": False,
            "policy_id": policy_id,
            "error": f"Policy {policy_id} not found in claims history.",
        }

    history = db[policy_id]
    approved = [c for c in history if c["verdict"] == "APPROVED"]
    denied = [c for c in history if c["verdict"] == "DENIED"]

    return {
        "found": True,
        "policy_id": policy_id,
        "total_claims": len(history),
        "approved_count": len(approved),
        "denied_count": len(denied),
        "total_approved_amount": sum(c["approved_amount"] for c in approved),
        "claims": history,
    }
