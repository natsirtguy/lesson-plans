"""The LLM boundary and its implementations."""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.llm.base import CacheableContext, LLMAdapter, LLMError, StructuredOutputError
from app.llm.fake import FakeLLMAdapter

__all__ = [
    "CacheableContext",
    "FakeLLMAdapter",
    "LLMAdapter",
    "LLMError",
    "StructuredOutputError",
    "build_adapter",
    "get_adapter",
]


def build_adapter(settings: Settings) -> LLMAdapter:
    """Construct the adapter the configuration asks for.

    The Anthropic client is imported lazily so that a fake-provider deployment --
    and the test suite -- never touches the SDK.

    :param settings: Runtime configuration.
    """
    if settings.llm_provider == "fake":
        return FakeLLMAdapter()
    from app.llm.anthropic_adapter import AnthropicAdapter

    return AnthropicAdapter(settings)


@lru_cache(maxsize=1)
def get_adapter() -> LLMAdapter:
    """Return the process-wide adapter, used as a FastAPI dependency."""
    return build_adapter(get_settings())
