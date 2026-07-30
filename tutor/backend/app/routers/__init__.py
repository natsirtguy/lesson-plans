"""HTTP routers.

Routers parse and validate input, delegate to a service, and shape the response.
Any conditional about mastery, scheduling, or graph integrity belongs in a service
instead.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers import ask, changesets, diagnostic, plans, reviews, schedule, subjects

#: Registered in this order by the application factory.
ROUTERS: tuple[APIRouter, ...] = (
    subjects.router,
    changesets.router,
    diagnostic.router,
    plans.router,
    reviews.router,
    schedule.router,
    ask.router,
)

__all__ = ["ROUTERS"]
