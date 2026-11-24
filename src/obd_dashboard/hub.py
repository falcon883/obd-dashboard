"""The Hub owns the live state of the current session and fans updates out to every browser tab."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import deque
from dataclasses import replace
from typing import Any, Callable, Deque, Dict, Optional, Set

from obd_dashboard.checkrun import run_check
from obd_dashboard.demo import run_demo, run_demo_check
from obd_dashboard.session import Session
from obd_dashboard.settings import Settings
from obd_dashboard.types import BaseSink, EventPayload, RowPayload
from obd_dashboard.userconfig import UserConfig

log = logging.getLogger(__name__)

HISTORY_SECONDS = 900  # the last 15 minutes are replayed to a tab that connects mid-session
HISTORY_ROWS = 6000  # ...but never more than this many rows, however fast the car answers
# Only what the live charts draw. The tiles and tables read the latest row, which carries everything.
CHART_KEYS = (
    "RPM", "SPEED", "COOLANT_TEMP", "SHORT_FUEL_TRIM_1", "LONG_FUEL_TRIM_1", "ENGINE_LOAD", "THROTTLE_POS", "battery_v",
)  # fmt: skip
EVENT_ROWS = 300
CLIENT_QUEUE = 500


class SessionBusy(RuntimeError):
    """A session is already running."""


class Hub(BaseSink):
    """Implements `Sink`. The logger thread calls on_*; browsers subscribe on the asyncio loop."""

    def __init__(
        self,
        settings: Settings,
        session_factory: Callable[..., Any] = Session,
        check_runner: Callable[..., Any] = run_check,
    ) -> None:
        self.settings = settings
        self._session_factory = session_factory
        self._check_runner = check_runner
        self._lock = threading.Lock()  # guards the state below (written by the logger thread)
        self._history: Deque[Dict[str, Any]] = deque(maxlen=HISTORY_ROWS)
        self._events: Deque[EventPayload] = deque(maxlen=EVENT_ROWS)
        self._status: Dict[str, Any] = {"state": "idle", "message": "Not started"}
        self._info: Optional[Dict[str, Any]] = None
        self._last: Optional[RowPayload] = None
        self._demo = False
        self._mode = "drive"
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._clients: Set[asyncio.Queue[str]] = set()  # only touched on the event loop

    # ---- browser side (event loop) ---------------------------------------------
    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=CLIENT_QUEUE)
        self._clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        self._clients.discard(q)

    def is_subscribed(self, q: asyncio.Queue[str]) -> bool:
        return q in self._clients

    def _deliver(self, message: str) -> None:
        for q in list(self._clients):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:  # slow client: drop it; its EventSource reconnects and resyncs
                self._clients.discard(q)

    def _broadcast(self, kind: str, payload: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        message = f"event: {kind}\ndata: {json.dumps(payload)}\n\n"
        loop.call_soon_threadsafe(self._deliver, message)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status": dict(self._status), "info": self._info, "history": list(self._history),
                "events": list(self._events), "last": self._last, "demo": self._demo,
                "running": self.running,
            }  # fmt: skip

    # ---- Sink (logger thread) --------------------------------------------------
    def on_row(self, row: RowPayload) -> None:
        with self._lock:
            self._last = row
            self._history.append({"t": row["t"], "v": {k: row["values"][k] for k in CHART_KEYS if k in row["values"]}})
            while self._history and row["t"] - self._history[0]["t"] > HISTORY_SECONDS:
                self._history.popleft()
        self._broadcast("row", row)

    def on_event(self, event: EventPayload) -> None:
        with self._lock:
            self._events.append(event)
        self._broadcast("alert", event)

    def on_status(self, state: str, message: str, result: Optional[Dict[str, Any]] = None) -> None:
        status: Dict[str, Any] = {"state": state, "message": message, "mode": self._mode}
        if result is not None:
            status["result"] = result
        with self._lock:
            self._status = status
        self._broadcast("status", status)

    def on_info(self, info: Dict[str, Any]) -> None:
        info = {**info, "demo": self._demo}
        with self._lock:
            self._info = info
        self._broadcast("info", info)

    # ---- session control ---------------------------------------------------------
    def start(self, port: Optional[str] = None, baud: int = 0, demo: bool = False, mode: str = "drive") -> None:
        """Begin a drive session, or with mode="check" a used-car check (a short, one-off read)."""
        with self._lock:
            if self.running:
                raise SessionBusy("A session is already running")
            self._history.clear()
            self._events.clear()
            self._info = self._last = None
            self._demo = demo
            self._mode = mode
            self._stop = threading.Event()
            cfg = replace(self.settings, com=port or self.settings.com, baud=baud)
            self._thread = threading.Thread(
                target=self._run, args=(cfg, demo, self._stop, mode), name="obd-session", daemon=True
            )
            self._thread.start()

    def end(self) -> None:
        self._stop.set()

    def join(self, timeout: float) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self, cfg: Settings, demo: bool, stop: threading.Event, mode: str = "drive") -> None:
        try:
            if mode == "check":
                if demo:
                    run_demo_check(self, stop, limits=UserConfig(cfg.output_dir).thresholds())
                else:
                    self._check_runner(cfg, self, stop)
            elif demo:
                run_demo(self, stop, limits=UserConfig(cfg.output_dir).thresholds())
            else:
                self._session_factory(cfg, self, stop).run()
        except Exception as exc:  # noqa: BLE001 - keep the server alive no matter what
            log.exception("session crashed")
            self.on_status("error", f"{type(exc).__name__}: {exc}")
        finally:
            if self._status["state"] not in ("error", "finished"):
                if mode == "check":  # cancelled before there was anything to report
                    self.on_status("idle", "Check cancelled")
                else:
                    self.on_status("finished", "Session finished", {"csv": None, "report": None, "summary": []})
