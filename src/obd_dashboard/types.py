"""Shared types: the JSON shapes sent to the browser and the sink interface sessions report to."""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Protocol

try:  # Python 3.9 compatibility
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict

LEVEL_RANK = {"WARN": 1, "CRIT": 2}


class Alert(NamedTuple):
    level: str  # "WARN" | "CRIT"
    msg: str


class Codes(TypedDict):
    mil: Optional[bool]
    stored: List[str]
    pending: List[str]


class EventPayload(TypedDict):
    time: str
    level: str
    msg: str


class RowPayload(TypedDict):
    t: float
    ts: str
    values: Dict[str, Any]
    alerts: Dict[str, List[str]]
    codes: Codes
    misfire: Dict[str, float]
    misfire0: Optional[float]
    warm: Dict[str, float]
    start_cool: Optional[float]


class Sink(Protocol):
    """Where a running session reports to (the web hub, the console, or a test)."""

    def on_status(self, state: str, message: str, result: Optional[Dict[str, Any]] = None) -> None: ...
    def on_info(self, info: Dict[str, Any]) -> None: ...
    def on_row(self, row: RowPayload) -> None: ...
    def on_event(self, event: EventPayload) -> None: ...


class BaseSink:
    """No-op sink to subclass; override only what you need."""

    def on_status(self, state: str, message: str, result: Optional[Dict[str, Any]] = None) -> None:
        pass

    def on_info(self, info: Dict[str, Any]) -> None:
        pass

    def on_row(self, row: RowPayload) -> None:
        pass

    def on_event(self, event: EventPayload) -> None:
        pass
