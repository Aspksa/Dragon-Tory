from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ObservationContext:
    trace_id: str | None = None
    module: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    document_id: str | None = None


_CURRENT: ContextVar[ObservationContext] = ContextVar(
    "tooru_observation_context",
    default=ObservationContext(),
)


def current_observation() -> ObservationContext:
    return _CURRENT.get()


@contextmanager
def observation_context(
    *,
    trace_id: str | None = None,
    module: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    document_id: str | None = None,
    new_trace: bool = False,
) -> Iterator[ObservationContext]:
    current = current_observation()
    resolved_trace = (
        uuid4().hex
        if new_trace
        else trace_id or current.trace_id or uuid4().hex
    )
    merged = ObservationContext(
        trace_id=resolved_trace,
        module=module or current.module,
        source_type=source_type or current.source_type,
        source_id=source_id or current.source_id,
        document_id=document_id or current.document_id,
    )
    token = _CURRENT.set(merged)
    try:
        yield merged
    finally:
        _CURRENT.reset(token)
