"""FastAPI application factory."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.routers import ROUTERS


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Takes settings as an argument rather than reading the singleton so tests can
    construct an app against a throwaway database without touching global state.

    :param settings: Configuration to use; falls back to the process singleton.
    """
    resolved = settings or get_settings()
    app = FastAPI(
        title="Adaptive Tutor",
        version="0.1.0",
        summary="Concept graphs, adaptive diagnostics, and spaced study planning.",
    )
    app.state.settings = resolved

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in ROUTERS:
        app.include_router(router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, Any]:
        """Report liveness and which LLM provider is configured."""
        return {
            "status": "ok",
            "llm_provider": resolved.llm_provider,
            "calendar_enabled": resolved.enable_calendar,
            "recovery_signal_enabled": resolved.enable_recovery_signal,
        }

    return app


app = create_app()
