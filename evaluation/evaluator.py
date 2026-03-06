import asyncio
import os
from typing import Optional, Tuple

from google import genai
from deepeval.models.base_model import DeepEvalBaseLLM
from deepeval.metrics import FaithfulnessMetric, HallucinationMetric

JUDGE_MODEL = "gemini-2.5-flash"


class GeminiJudge(DeepEvalBaseLLM):
    """DeepEval-compatible wrapper for Gemini using GOOGLE_API_KEY."""

    def __init__(self, model: str = JUDGE_MODEL):
        self.model_name = model
        self._client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

    def load_model(self):
        return self._client

    def generate(self, prompt: str, schema: Optional[type] = None) -> Tuple[str, float]:
        client = self.load_model()
        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )
        return response.text, 0.0  # (response_text, cost)

    async def a_generate(self, prompt: str, schema: Optional[type] = None) -> Tuple[str, float]:
        return await asyncio.to_thread(self.generate, prompt, schema)

    def get_model_name(self) -> str:
        return self.model_name


def build_metrics(judge: GeminiJudge) -> list:
    faithfulness = FaithfulnessMetric(
        threshold=0.7,
        model=judge,
        include_reason=True,
    )

    hallucination = HallucinationMetric(
        threshold=0.5,
        model=judge,
        include_reason=True,
    )

    return [faithfulness, hallucination]
