"""Mock LLM adapter for testing — returns deterministic responses without API calls."""
from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from app.infrastructure.llm.base import BaseLLMAdapter

T = TypeVar("T", bound=BaseModel)

# A valid LLMAgentResponse — used by complete_structured() and complete_text()
# so SeniorDeveloperAgent succeeds without a real API call.
_MOCK_AGENT_JSON = {
    "score": 75,
    "summary": "Mock review: the repository follows reasonable coding conventions with minor issues.",
    "confidence": 0.8,
    "confidence_reason": "Sufficient signal from file tree and metrics.",
    "issues": [
        {
            "severity": "Low",
            "file_path": None,
            "line_number": None,
            "title": "Mock issue",
            "description": "This is a mock issue returned by the test adapter.",
            "recommendation": "No action needed — this is a test stub.",
        }
    ],
    "recommendations": [
        "Add type annotations to all public functions.",
        "Enforce linting in CI.",
    ],
}


class MockLLMAdapter(BaseLLMAdapter):
    """
    Deterministic mock for unit tests and local development without an API key.

    complete_structured() returns a validated instance of the response_model
    using the shared _MOCK_AGENT_JSON fixture when the model matches, otherwise
    falls back to building a minimal stub from the JSON schema.
    complete_text() returns the same data serialised as JSON string.
    """

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
    ) -> T:
        # Try the pre-built fixture first (satisfies LLMAgentResponse constraints)
        try:
            return response_model.model_validate(_MOCK_AGENT_JSON)
        except Exception:
            # Fallback for other models: build a minimal stub from the JSON schema
            schema = response_model.model_json_schema()
            stub_data = self._build_stub(schema)
            return response_model.model_validate(stub_data)

    async def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        import json
        return json.dumps(_MOCK_AGENT_JSON)

    @staticmethod
    def _build_stub(schema: dict) -> dict:  # type: ignore[type-arg]
        result = {}
        for prop, definition in schema.get("properties", {}).items():
            t = definition.get("type", "string")
            if t == "string":
                result[prop] = "stub"
            elif t == "integer":
                result[prop] = 75
            elif t == "number":
                result[prop] = 75.0
            elif t == "boolean":
                result[prop] = True
            elif t == "array":
                result[prop] = []
            elif t == "object":
                result[prop] = {}
        return result
