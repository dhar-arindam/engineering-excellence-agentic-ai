"""OpenAI-compatible LLM adapter using the official async client."""
from __future__ import annotations

import json
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.exceptions import LLMError
from app.core.logging import get_logger
from app.infrastructure.llm.base import BaseLLMAdapter

T = TypeVar("T", bound=BaseModel)

logger = get_logger(__name__)


class OpenAIAdapter(BaseLLMAdapter):
    """
    Async OpenAI adapter with retry logic and structured output parsing.

    Compatible with any OpenAI-spec API (Azure OpenAI, local Ollama, etc.)
    by overriding base_url in settings.
    """

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,  # handled by tenacity below
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
    ) -> T:
        logger.debug("llm.complete_structured", model=settings.openai_model)
        try:
            response = await self._client.chat.completions.create(
                model=settings.openai_model,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"{user_prompt}\n\nRespond with a JSON object matching "
                            f"this schema:\n{json.dumps(response_model.model_json_schema(), indent=2)}"
                        ),
                    },
                ],
            )
            raw = response.choices[0].message.content or "{}"
            return response_model.model_validate_json(raw)
        except Exception as exc:
            raise LLMError(str(exc)) from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        logger.debug("llm.complete_text", model=settings.openai_model)
        try:
            response = await self._client.chat.completions.create(
                model=settings.openai_model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            raise LLMError(str(exc)) from exc
