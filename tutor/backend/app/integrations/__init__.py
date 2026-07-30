"""Optional integrations, behind feature flags, with null defaults.

Two capabilities the spec marks optional: writing sessions to a calendar, and
biasing hard sessions toward days a recovery signal says the learner is fresh.
Neither ships with a real provider -- there is no calendar account to talk to and
no wearable to read -- so what exists here is the *seam*: a Protocol per
capability, a null implementation that is always safe to call, and a resolver that
returns the null one unless a flag is set.

That is worth having rather than deferring, for one reason. The alternative is a
scattering of ``if settings.enable_calendar:`` checks written when a provider
finally appears, and by then the call sites are load-bearing and the shape of the
integration has to be reverse-engineered from them. Here the call sites already
exist and are exercised on every schedule build; adding a provider is implementing
one Protocol.

Be honest about what this is: enabling the flags today changes nothing observable
beyond the ``/health`` payload, because the only providers are the null ones.
"""

from __future__ import annotations

from app.config import Settings
from app.integrations.base import (
    CalendarSink,
    NullCalendarSink,
    NullRecoverySignal,
    RecoverySignal,
    ScheduledEvent,
)

__all__ = [
    "CalendarSink",
    "NullCalendarSink",
    "NullRecoverySignal",
    "RecoverySignal",
    "ScheduledEvent",
    "get_calendar_sink",
    "get_recovery_signal",
]


def get_calendar_sink(settings: Settings) -> CalendarSink:
    """Return the configured calendar sink.

    :param settings: Runtime configuration.
    """
    # No real provider exists yet; the flag selects between "null" and "null".
    # When one is written, this is the only place that has to change.
    return NullCalendarSink()


def get_recovery_signal(settings: Settings) -> RecoverySignal:
    """Return the configured recovery signal.

    :param settings: Runtime configuration.
    """
    return NullRecoverySignal()
