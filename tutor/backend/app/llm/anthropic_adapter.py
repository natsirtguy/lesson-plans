"""The real :class:`~app.llm.base.LLMAdapter`, backed by the Anthropic SDK.

This is the only module in the app that imports ``anthropic``.

Three choices worth explaining, since they are not obvious from the code:

* **Structured output uses ``output_config.format`` with a JSON Schema**, not a
  forced tool call. The endpoint constrains generation to the schema, so the
  output parses by construction; a forced tool call only *asks* for the shape.
  Validation still runs, and a failure retries once with the error fed back.
* **The cacheable context is its own system block** carrying ``cache_control``.
  Caching is a prefix match, so the stable concept graph and mastery summary go
  in front and the volatile per-call instruction goes in the user turn.
* **Refusals are checked before content is read.** The safety classifiers return
  HTTP 200 with ``stop_reason == "refusal"`` and possibly an empty content list,
  so indexing ``content[0]`` first would raise on a perfectly valid response.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from app.config import Settings
from app.llm.base import (
    CacheableContext,
    LLMError,
    SchemaT,
    StructuredOutputError,
)
from app.llm.schema_tools import response_schema

#: Beta flag gating the server-side refusal fallback parameter.
FALLBACK_BETA = "server-side-fallback-2026-06-01"

#: The SDK's typed signatures do not yet cover every beta field used here
#: (``fallbacks``, and ``format`` inside ``output_config``), so the request is
#: assembled as a dict and the call site is cast. Keep the cast at the call, not
#: on the client, so everything else stays type-checked.


class AnthropicAdapter:
    """Adapter over the async Anthropic client."""

    def __init__(self, settings: Settings, client: AsyncAnthropic | None = None) -> None:
        """
        :param settings: Runtime configuration supplying model, key, and limits.
        :param client: Pre-built client, injected by tests that stub the transport.
        """
        self._settings = settings
        self._client = client or AsyncAnthropic(
            api_key=settings.anthropic_api_key or None,
            timeout=settings.llm_timeout_seconds,
        )

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

        Retries exactly once, feeding the validation error back to the model,
        before giving up.

        :param schema: Pydantic model describing the expected output.
        :param system: System prompt, excluding the cacheable context.
        :param prompt: The user-turn instruction.
        :param task: Short identifier for logging.
        :param context: Optional cacheable prefix.
        :param max_tokens: Override for the configured output ceiling.
        :param reasoning: Whether to use the higher reasoning effort.
        :raises StructuredOutputError: If validation fails on both attempts.
        """
        effort = self._settings.llm_reasoning_effort if reasoning else self._settings.llm_effort
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        params: dict[str, Any] = {
            "model": self._settings.llm_model,
            "max_tokens": max_tokens or self._settings.llm_max_tokens,
            "system": self._system_blocks(system, context),
            "output_config": {
                "effort": effort,
                "format": {"type": "json_schema", "schema": response_schema(schema)},
            },
        }
        params.update(self._fallback_params())

        last_error: ValidationError | None = None
        for attempt in (1, 2):
            create = cast(Any, self._client.beta.messages.create)
            message = await create(messages=messages, **params)
            text = self._extract_text(message, task=task)
            try:
                return schema.model_validate_json(text)
            except ValidationError as exc:
                last_error = exc
                if attempt == 2:
                    break
                messages = [
                    *messages,
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": (
                            "That output failed schema validation with the following "
                            f"errors:\n{exc}\n\nEmit corrected output that satisfies the "
                            "schema. Change only what the errors require."
                        ),
                    },
                ]

        raise StructuredOutputError(
            f"task={task} schema={schema.__name__} failed validation twice: {last_error}"
        )

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

        :param system: System prompt, excluding the cacheable context.
        :param prompt: The user-turn instruction.
        :param task: Short identifier for logging.
        :param context: Optional cacheable prefix.
        :param max_tokens: Override for the configured streaming ceiling.
        """
        return self._stream(
            system=system,
            prompt=prompt,
            task=task,
            context=context,
            max_tokens=max_tokens,
        )

    async def _stream(
        self,
        *,
        system: str,
        prompt: str,
        task: str,
        context: CacheableContext | None,
        max_tokens: int | None,
    ) -> AsyncIterator[str]:
        """Drive the SDK's streaming helper and yield text deltas.

        :param system: System prompt, excluding the cacheable context.
        :param prompt: The user-turn instruction.
        :param task: Short identifier for logging.
        :param context: Optional cacheable prefix.
        :param max_tokens: Override for the configured streaming ceiling.
        """
        params: dict[str, Any] = {
            "model": self._settings.llm_model,
            "max_tokens": max_tokens or self._settings.llm_stream_max_tokens,
            "system": self._system_blocks(system, context),
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": self._settings.llm_effort},
        }
        params.update(self._fallback_params())

        stream_call = cast(Any, self._client.beta.messages.stream)
        async with stream_call(**params) as stream:
            async for delta in stream.text_stream:
                yield delta
            final = await stream.get_final_message()
        if getattr(final, "stop_reason", None) == "refusal":
            raise LLMError(f"task={task} was declined by the model's safety classifiers")

    def _system_blocks(self, system: str, context: CacheableContext | None) -> list[dict[str, Any]]:
        """Assemble system blocks with the cacheable prefix marked.

        The instruction block comes first and the reusable context second, so a
        change to the short instruction does not invalidate the long prefix.

        :param system: System prompt, excluding the cacheable context.
        :param context: Optional cacheable prefix.
        """
        blocks: list[dict[str, Any]] = [{"type": "text", "text": system}]
        if context is not None:
            block: dict[str, Any] = {"type": "text", "text": context.text}
            if self._settings.prompt_caching:
                block["cache_control"] = {"type": "ephemeral"}
            blocks.append(block)
        return blocks

    def _fallback_params(self) -> dict[str, Any]:
        """Build the server-side refusal-fallback parameters, if enabled."""
        if not self._settings.llm_server_side_fallback:
            return {}
        return {
            "betas": [FALLBACK_BETA],
            "fallbacks": [{"model": self._settings.llm_fallback_model}],
        }

    @staticmethod
    def _extract_text(message: object, *, task: str) -> str:
        """Pull the text payload out of a completed message.

        :param message: The SDK message object.
        :param task: Short identifier, included in raised errors.
        :raises LLMError: If the request was refused or produced no text.
        """
        if getattr(message, "stop_reason", None) == "refusal":
            raise LLMError(f"task={task} was declined by the model's safety classifiers")
        blocks = cast(list[Any], getattr(message, "content", []))
        parts = [b.text for b in blocks if getattr(b, "type", None) == "text"]
        if not parts:
            raise LLMError(f"task={task} returned no text content")
        return "".join(parts)
