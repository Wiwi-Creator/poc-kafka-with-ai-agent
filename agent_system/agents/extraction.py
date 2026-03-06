from google.adk.agents import Agent
from pydantic import BaseModel, Field
from typing import Literal

from token_tracker import tracker


class ExtractionResult(BaseModel):
    """Structured output from the Extraction Agent."""

    surgery_type: str = Field(description="Type of surgery or medical procedure performed")
    disease: str = Field(description="Primary diagnosed condition or disease")
    hospitalization_days: int = Field(description="Number of days hospitalized (0 if outpatient)")
    severity: Literal["low", "medium", "high"] = Field(
        description="Clinical severity: low=outpatient/minor, medium=standard surgery, high=emergency/ICU"
    )


EXTRACTION_INSTRUCTION = """
You are a medical claim extraction specialist.

Your task is to analyze the diagnosis text from an insurance claim and extract
structured medical features.

Rules:
- Extract the EXACT surgery or procedure name mentioned in the text.
- Identify the primary disease or condition that led to the procedure.
- Count the hospitalization days explicitly mentioned. If "outpatient" or no
  hospitalization is mentioned, use 0.
- Assess severity:
  - "low": outpatient procedures, minor treatments, screenings
  - "medium": standard surgeries with 1-3 days hospitalization
  - "high": emergency procedures, ICU stays, 4+ days hospitalization

Return ONLY the structured JSON output. Do not add any commentary.
"""


extraction_agent = Agent(
    name="extraction_agent",
    model="gemini-2.5-flash",
    instruction=EXTRACTION_INSTRUCTION,
    output_schema=ExtractionResult,
    tools=[],
    after_model_callback=tracker.create_callback("extraction_agent"),
)
