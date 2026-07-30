"""The LLM boundary.

Everything the app asks a model to do goes through :class:`LLMAdapter`. Services
and routers never import the Anthropic SDK, which is what makes the whole test
suite runnable with zero network calls.

Two capabilities, and only two:

* :meth:`LLMAdapter.generate_structured` for anything the app parses -- concept
  graphs, quiz items, grades, classifications. Always tool-use against a Pydantic
  schema, never "please return JSON".
* :meth:`LLMAdapter.stream_text` for prose the learner reads -- lessons,
  explanations, feedback. Streams so the UI can render as it arrives.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class CacheableContext:
    """A long, reusable prompt prefix worth caching provider-side.

    In practice this is the concept graph plus the learner's mastery summary,
    which form the shared prefix of nearly every call for a subject.

    :param key: Stable identity of this context, used by the fake adapter and by
        logs to tell one cached prefix from another.
    :param text: The prefix content itself.
    """

    key: str
    text: str


class LLMError(RuntimeError):
    """Raised when the model cannot produce usable output."""


class StructuredOutputError(LLMError):
    """Raised when structured output fails schema validation twice."""


class LLMAdapter(Protocol):
    """The contract every model backend implements."""

    async def generate_structured(
        self,
        *,
        schema: type[SchemaT],
        system: str,
        prompt: str,
        task: str,
        context: CacheableContext | None = None,
        max_tokens: int | None = None,
        reasoning: bool = False,
    ) -> SchemaT:
        """Generate a validated instance of ``schema``.

        Implementations must validate the model's output against the schema and
        retry exactly once on validation failure before raising.

        :param schema: Pydantic model describing the expected output.
        :param system: System prompt, excluding the cacheable context.
        :param prompt: The user-turn instruction.
        :param task: Short identifier for logging and model routing.
        :param context: Optional cacheable prefix.
        :param max_tokens: Override for the configured output ceiling.
        :param reasoning: Whether to route to the stronger, slower model.
        :raises StructuredOutputError: If validation fails on both attempts.
        """
        ...

    def stream_text(
        self,
        *,
        system: str,
        prompt: str,
        task: str,
        context: CacheableContext | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Stream prose as a sequence of text deltas.

        Not an ``async def``: implementations return an async iterator directly so
        callers can pass it straight to an SSE response without an extra await.

        :param system: System prompt, excluding the cacheable context.
        :param prompt: The user-turn instruction.
        :param task: Short identifier for logging and model routing.
        :param context: Optional cacheable prefix.
        :param max_tokens: Override for the configured output ceiling.
        """
        ...
