"""Shared schema configuration.

API schemas are separate from ORM models throughout. The ORM describes what is
stored; these describe what is exchanged. Collapsing the two makes every storage
decision a public API decision.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base class for request and response schemas."""

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        populate_by_name=True,
    )
