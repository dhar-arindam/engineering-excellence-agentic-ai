"""LLM adapter interface and implementations."""
from __future__ import annotations

import abc
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class BaseLLMAdapter(abc.ABC):
    """
    Abstract interface for LLM completions.

    All agents interact with the LLM exclusively through this interface,
    ensuring infrastructure details never leak into the application layer.
    """

    @abc.abstractmethod
    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
    ) -> T:
        """
        Send a prompt and parse the response into a Pydantic model.

        Args:
            system_prompt: Role/context for the LLM.
            user_prompt: The specific task/question.
            response_model: Pydantic model class to parse response into.
            temperature: Sampling temperature (lower = more deterministic).

        Returns:
            Validated instance of response_model.

        Raises:
            LLMError: On API failure or unparseable response.
        """

    @abc.abstractmethod
    async def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        """Send a prompt and return raw text response."""
