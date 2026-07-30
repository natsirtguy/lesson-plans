"""Application configuration, sourced from the environment and ``.env``."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Every tunable constant of the learning model is exposed here rather than
    hard-coded, because they are the knobs that need adjusting once real answer
    data exists.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TUTOR_",
        extra="ignore",
    )

    # --- infrastructure ------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./tutor.db"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    debug: bool = False

    # --- LLM -----------------------------------------------------------------
    anthropic_api_key: str = ""
    llm_provider: Literal["anthropic", "fake"] = "anthropic"
    llm_model: str = "claude-opus-5"
    llm_max_tokens: int = 16000
    #: Streaming responses can afford a much larger ceiling than blocking ones.
    llm_stream_max_tokens: int = 64000
    llm_timeout_seconds: float = 600.0
    prompt_caching: bool = True
    #: Reasoning depth. Structured extraction does not need the default "high".
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    #: Effort for calls that genuinely reason: graph decomposition, plan sequencing.
    llm_reasoning_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    #: Server-side refusal fallback. The safety classifiers on the primary model can
    #: decline a request; when they do, the API reruns it on this model in the same
    #: call rather than handing back an empty response.
    llm_server_side_fallback: bool = True
    llm_fallback_model: str = "claude-opus-4-8"

    # --- mastery model -------------------------------------------------------
    #: Base Elo step size. Scaled up by item difficulty and down by confidence.
    elo_base_step: float = 0.28
    #: Logistic scale for the expected-score curve; larger means sharper.
    elo_logistic_scale: float = 4.0
    #: Fraction of remaining uncertainty removed by one on-node observation.
    confidence_gain: float = 0.34
    #: Per-hop attenuation when propagating evidence through prerequisite edges.
    propagation_decay: float = 0.5
    #: Hops beyond which propagation is not worth computing.
    propagation_max_hops: int = 3
    #: Mastery assigned to a brand-new node before any evidence, if it has no prereqs.
    default_seed_mastery: float = 0.15
    #: Confidence assigned to a node seeded from its prerequisites.
    seeded_confidence: float = 0.12
    #: Confidence multiplier applied to each child of a split node.
    split_confidence_factor: float = 0.5
    #: Days for mastery to decay halfway toward its floor without retrieval.
    mastery_half_life_days: float = 60.0
    #: Days for confidence to halve without retrieval.
    confidence_half_life_days: float = 45.0
    #: Mastery at or above this counts as "covered" for reporting.
    mastery_threshold: float = 0.7

    # --- diagnostic ----------------------------------------------------------
    diagnostic_max_items: int = 30
    diagnostic_min_items: int = 8
    diagnostic_confidence_target: float = 0.55

    # --- scheduling ----------------------------------------------------------
    target_retention: float = 0.85
    daily_review_cap: int = 20
    default_days_per_week: int = 4
    default_minutes_per_session: int = 20
    #: Minutes budgeted for opening retrieval in a 20-minute session.
    session_retrieval_minutes: int = 5
    #: Wall-clock minutes a single review item is assumed to take.
    minutes_per_review_item: float = 0.5
    #: Wall-clock minutes a single new concept is assumed to take.
    minutes_per_new_node: float = 7.0
    #: Retrieval success above this means intervals are too short.
    calibration_high_watermark: float = 0.90
    #: Retrieval success below this means intervals are too long.
    calibration_low_watermark: float = 0.75
    #: Minimum graded retrievals before calibration advice is offered.
    calibration_min_samples: int = 12

    # --- feature flags -------------------------------------------------------
    enable_calendar: bool = False
    enable_recovery_signal: bool = False

    @property
    def is_sqlite(self) -> bool:
        """Whether the configured database is SQLite."""
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
