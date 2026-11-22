from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any, Optional

import pytest

from obd_dashboard.settings import Settings, Tuning
from obd_dashboard.types import BaseSink


class RecordingSink(BaseSink):
    """Collects everything a session reports; optionally stops the session after N rows."""

    def __init__(self, stop: Optional[threading.Event] = None, stop_after_rows: Optional[int] = None) -> None:
        self.rows: list[Any] = []
        self.events: list[Any] = []
        self.statuses: list[tuple[str, str, Any]] = []
        self.infos: list[Any] = []
        self._stop, self._limit = stop, stop_after_rows

    def on_row(self, row: Any) -> None:
        self.rows.append(row)
        if self._stop is not None and self._limit is not None and len(self.rows) >= self._limit:
            self._stop.set()

    def on_event(self, event: Any) -> None:
        self.events.append(event)

    def on_status(self, state: str, message: str, result: Any = None) -> None:
        self.statuses.append((state, message, result))

    def on_info(self, info: Any) -> None:
        self.infos.append(info)

    @property
    def states(self) -> list[str]:
        return [s[0] for s in self.statuses]


FAST_TUNING = Tuning(
    extra_per_loop=3, slow_every=0.0, target_loop=0.0, lost_after=3, reconnect_tries=2, reconnect_wait=0.0
)


@pytest.fixture
def settings(tmp_path: Any) -> Settings:
    return replace(
        Settings(), output_dir=tmp_path / "logs", beep=False, open_browser=False, lookup_vin=False, tuning=FAST_TUNING
    )
