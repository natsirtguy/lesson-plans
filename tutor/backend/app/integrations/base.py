"""Protocols for the optional integrations, and their null implementations.

A null implementation is not a stub that raises: it is a real implementation of
"this capability is switched off". Calling it is always safe, and the caller does
not branch on whether a provider exists. That is what keeps the feature flag from
leaking into the scheduler as a scattering of conditionals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ScheduledEvent:
    """One planned sitting, in the shape a calendar wants.

    :param on: The day it is planned for.
    :param minutes: How long it is expected to take.
    :param title: What to call it in the calendar.
    :param description: Longer detail: what the session covers.
    """

    on: date
    minutes: int
    title: str
    description: str


class CalendarSink(Protocol):
    """Somewhere planned sittings can be written."""

    @property
    def enabled(self) -> bool:
        """Whether writes actually go anywhere."""
        ...

    async def publish(self, event: ScheduledEvent, *, existing_id: str | None) -> str | None:
        """Create or update one calendar entry, returning its external id.

        :param event: The sitting to write.
        :param existing_id: The id of a previously written entry to update.
        """
        ...


class RecoverySignal(Protocol):
    """A per-day readiness score, from sleep, HRV, or anything similar."""

    @property
    def enabled(self) -> bool:
        """Whether the signal has anything to say."""
        ...

    async def score_for(self, day: date) -> float | None:
        """Readiness on one day in [0, 1], or None when unknown.

        :param day: The day to score.
        """
        ...


class NullCalendarSink:
    """A calendar sink that writes nowhere.

    Returns ``None`` rather than a fabricated id, so ``calendar_event_id`` stays
    null and nothing downstream believes an entry exists.
    """

    @property
    def enabled(self) -> bool:
        """Always false."""
        return False

    async def publish(self, event: ScheduledEvent, *, existing_id: str | None) -> str | None:
        """Discard the event and report that nothing was written.

        :param event: Ignored.
        :param existing_id: Ignored.
        """
        return None


class NullRecoverySignal:
    """A recovery signal that never has an opinion.

    Returns ``None`` rather than a neutral 0.5, because those mean different
    things: 0.5 is "an average day", ``None`` is "no idea", and a scheduler that
    conflates them will happily bias a plan on a number nobody measured.
    """

    @property
    def enabled(self) -> bool:
        """Always false."""
        return False

    async def score_for(self, day: date) -> float | None:
        """Report that nothing is known about this day.

        :param day: Ignored.
        """
        return None
