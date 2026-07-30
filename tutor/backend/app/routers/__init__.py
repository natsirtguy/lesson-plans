"""HTTP routers.

Routers parse and validate input, delegate to a service, and shape the response.
Any conditional about mastery, scheduling, or graph integrity belongs in a service
instead.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers import changesets, diagnostic, subjects

#: Registered in this order by the application factory.
ROUTERS: tuple[APIRouter, ...] = (
    subjects.router,
    changesets.router,
    diagnostic.router,
)

__all__ = ["ROUTERS"]
