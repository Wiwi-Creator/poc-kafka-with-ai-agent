import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
)

from orchestrator import process_claim


TEST_CLAIM = {
    "claim_id": "CLM-001",
    "policy_id": "POL-A100",
    "patient_name": "Wang Xiao-Ming",
    "diagnosis_text": (
        "Patient admitted for acute appendicitis with peritoneal irritation signs. "
        "Underwent laparoscopic appendectomy under general anesthesia. "
        "Hospitalized for 3 days with uneventful recovery. "
        "Discharged with oral antibiotics."
    ),
    "claim_amount": 50000,
    "submitted_at": "2025-01-15T10:30:00Z",
}


async def main():
    print(f"\nClaim: {TEST_CLAIM['claim_id']}")
    print(f"Policy: {TEST_CLAIM['policy_id']}")
    print(f"Amount: {TEST_CLAIM['claim_amount']}")
    print(f"Diagnosis: {TEST_CLAIM['diagnosis_text'][:80]}...")
    print()

    decision = await process_claim(TEST_CLAIM)

    print(" DECISION RESULT")
    print(json.dumps(decision, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
