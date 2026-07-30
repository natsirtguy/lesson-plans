"""Server-sent events.

Every payload is JSON, including text deltas. That is not ceremony: an SSE frame
is newline-delimited, so a delta containing a newline would silently split into two
frames if it were sent raw. JSON-encoding it makes every event exactly one
``data:`` line and removes the whole class of bug.

Three event names are used throughout. ``meta`` carries everything the client needs
before the prose starts -- what was asked, what it was classified as, which lesson
row the content is being written to. ``delta`` carries text. ``done`` carries the
result. A failure mid-stream arrives as ``error``, because the HTTP status was
committed long before it happened.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence

from fastapi.responses import StreamingResponse

#: What an event payload may be. Deliberately narrow rather than ``Any``: every
#: payload in this app is either a text delta or a dumped Pydantic model.
Payload = str | int | float | bool | None | Mapping[str, object] | Sequence[object]

#: Headers that keep a stream a stream. ``X-Accel-Buffering`` is what stops nginx
#: and similar proxies buffering the whole response and defeating the point.
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse(name: str, data: Payload) -> str:
    """Format one server-sent event.

    :param name: The event name the client dispatches on.
    :param data: Payload, JSON-encoded. Non-serialisable values fall back to str.
    """
    body = json.dumps(data, default=str, separators=(",", ":"))
    return f"event: {name}\ndata: {body}\n\n"


def stream(events: AsyncIterator[str]) -> StreamingResponse:
    """Wrap an event generator in a streaming HTTP response.

    :param events: Pre-formatted SSE frames.
    """
    return StreamingResponse(events, media_type="text/event-stream", headers=SSE_HEADERS)


def parse_events(payload: str) -> list[tuple[str, Payload]]:
    """Parse an SSE body back into (name, data) pairs.

    Lives here rather than in the tests because it is the inverse of :func:`sse`
    and the two should not be able to drift apart.

    :param payload: A complete SSE response body.
    """
    events: list[tuple[str, Payload]] = []
    for frame in payload.split("\n\n"):
        name: str | None = None
        data: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data.append(line.removeprefix("data: "))
        if name is not None:
            events.append((name, json.loads("".join(data)) if data else None))
    return events
