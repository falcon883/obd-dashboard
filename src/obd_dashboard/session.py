"""One logging session: connect, baseline, poll loop, alerts, files, summary. Read-only."""

from __future__ import annotations

import datetime
import logging
import threading
import time
from dataclasses import asdict, replace
from typing import Any, Callable, Dict, List, Optional

from obd_dashboard import __version__, connection, readers
from obd_dashboard.garage import VERDICTS, Car, Garage
from obd_dashboard.notify import beep
from obd_dashboard.readers import C, SensorPlan, fmt_monitors, fmt_supported
from obd_dashboard.report import SessionFiles, Stat, SummaryData, column_name, csv_fields, render_summary
from obd_dashboard.rules import RuleState, evaluate
from obd_dashboard.settings import Settings
from obd_dashboard.types import LEVEL_RANK, Alert, BaseSink, Codes, EventPayload, RowPayload, Sink
from obd_dashboard.userconfig import DEFAULT_THRESHOLDS, TUNING_KEYS, UserConfig
from obd_dashboard.vin import CarInfo, decode_nhtsa, normalize_vin

log = logging.getLogger(__name__)

WARM_CHECKPOINTS_C = (70, 80, 85)
DRIVING_KPH = 15
KPH_TO_MPH = 0.621371
NO_CAR_MESSAGE = (
    "Could not talk to the car. Check: adapter fully seated, MS/HS switch on HS, "
    "ignition ON, no other app using the port."
)


class SafeSink(BaseSink):
    """Wraps a sink so a broken subscriber can never stop the logger."""

    def __init__(self, inner: Sink) -> None:
        self._inner = inner

    def _call(self, name: str, *args: Any) -> None:
        try:
            getattr(self._inner, name)(*args)
        except Exception:  # noqa: BLE001
            log.exception("sink.%s failed", name)

    def on_status(self, state: str, message: str, result: Optional[Dict[str, Any]] = None) -> None:
        self._call("on_status", state, message, result)

    def on_info(self, info: Dict[str, Any]) -> None:
        self._call("on_info", info)

    def on_row(self, row: RowPayload) -> None:
        self._call("on_row", row)

    def on_event(self, event: EventPayload) -> None:
        self._call("on_event", event)


class Session:
    """Run with `Session(settings, sink, stop).run()`. Set `stop` to end it cleanly (files get finalised)."""

    def __init__(
        self,
        settings: Settings,
        sink: Sink,
        stop: Optional[threading.Event] = None,
        *,
        connector: Callable[[Optional[str], int], Any] = connection.open_connection,
        notifier: Optional[Callable[[str], None]] = None,
        clock: Callable[[], float] = time.monotonic,
        vin_lookup: Callable[[str], Optional[CarInfo]] = decode_nhtsa,
    ) -> None:
        self.cfg = settings
        # Options saved from the Settings screen. Anything never changed there leaves `settings` untouched,
        # and a command-line switch that turns something off still wins.
        self.config = UserConfig(settings.output_dir)
        saved = self.config.advanced()
        changed = self.config.advanced_overrides()
        self.tune = replace(settings.tuning, **{k: changed[k] for k in TUNING_KEYS if k in changed})
        self._lookup_vin = settings.lookup_vin and bool(saved["lookup_vin"])
        beep_on = settings.beep and bool(saved["beep"])
        self.sink = SafeSink(sink)
        self.stop = stop or threading.Event()
        self._connector = connector
        self._notify = notifier if notifier is not None else (beep if beep_on else (lambda _l: None))
        self._clock = clock
        self._vin_lookup = vin_lookup
        self.garage = Garage(settings.output_dir)
        self.car: Car = Car(vin="")
        self._lookup_result: List[Optional[CarInfo]] = []  # filled by the lookup thread, read in the loop
        self._lookup_pending = False
        self._started = ""

        self.conn: Any = None
        self.port = ""
        self.baud = 0
        self.plan = SensorPlan()
        self.files: Optional[SessionFiles] = None
        self.limits = DEFAULT_THRESHOLDS  # replaced once we know which car this is
        self.state = RuleState()
        self.readings: Dict[str, Any] = {}
        self.units: Dict[str, str] = {}
        self.stats: Dict[str, Stat] = {}
        self.static_start: Dict[str, Any] = {}
        self.active: Dict[str, Alert] = {}
        self.raised: List[str] = []
        self.worst = 0
        self.warm: Dict[int, float] = {}
        self.start_cool: Optional[float] = None
        self.loops = 0
        self._rotate = 0
        self._empty = 0
        self._columns: Dict[str, str] = {}
        self._t0 = 0.0

    # ---- public ------------------------------------------------------------
    def run(self) -> None:
        port = self.cfg.com or connection.find_port()
        if port is None:
            self.sink.on_status("error", "No serial port found. Plug in the adapter and try again.")
            return
        self.sink.on_status("connecting", f"Connecting on {port}...")
        self.conn = self._connector(port, self.cfg.baud)
        if self.conn is None:
            log.error(NO_CAR_MESSAGE)
            self.sink.on_status("error", NO_CAR_MESSAGE)
            return
        try:
            self.port, self.baud = connection.link_info(self.conn, port, self.cfg.baud)
            self.sink.on_status("connected", f"Connected on {self.port} @ {self.baud}")
            self._identify()
            with SessionFiles(self.garage.car_dir(self.car.vin)) as files:
                self.files = files
                self._baseline()
                self._loop()
                self._finish()
        finally:
            if self.conn is not None:
                self.conn.close()

    # ---- start-up ------------------------------------------------------------
    def _identify(self) -> None:
        """Work out which sensors exist and WHICH CAR this is, so files go into that car's folder."""
        conn = self.conn
        self.plan = readers.plan_sensors(conn)
        p = self.plan
        log.info("Sensors: %d fast + %d rotating | Mode 06 tests: %d", len(p.fast), len(p.rest), len(p.monitors))
        self.static_start = readers.read_static(conn, p.statics)
        vin = normalize_vin(self.static_start.get("VIN"))
        if vin is None:
            log.warning("VIN not readable (%r): logging under '%s'", self.static_start.get("VIN"), "unknown-car")
        self.car = self.garage.register(vin)
        log.info("Car: %s%s", self.car.display_name, f" ({vin})" if vin else "")
        self.limits = self.config.thresholds(vin)  # defaults + your global edits + this car's edits
        self.state = RuleState.for_limits(self.limits)
        if vin and self._lookup_vin and not self.car.model:
            self._lookup_pending = True
            threading.Thread(target=self._lookup_worker, args=(vin,), daemon=True, name="vin-lookup").start()

    def _lookup_worker(self, vin: str) -> None:
        self._lookup_result.append(self._vin_lookup(vin))  # list.append is atomic: safe across threads

    def _poll_lookup(self) -> None:
        """Called from the main loop: apply the NHTSA answer (if any) and tell the UI."""
        if not (self._lookup_pending and self._lookup_result):
            return
        self._lookup_pending = False
        found = self._lookup_result[0]
        if found is None:
            return
        self.car = self.garage.apply_decode(self.car, found)
        log.info("Car identified: %s", self.car.title)
        self._files().log(f"Car identified (NHTSA): {self.car.title} {self.car.engine or ''}".rstrip())
        self.sink.on_info(self._info())

    def _baseline(self) -> None:
        conn, files, p = self.conn, self._files(), self.plan
        files.log(f"OBD session {files.stamp} | port {self.port} | protocol {conn.protocol_name()}")
        adapter = readers.query(conn, C.ELM_VERSION)
        files.log(f"Adapter: {adapter.value if not adapter.is_null() else 'unknown'}")
        files.log(f"Car: {self.car.display_name} | VIN {self.car.vin or 'unknown'}")
        custom = {k: v for k, v in asdict(self.limits).items() if v != getattr(DEFAULT_THRESHOLDS, k)}
        files.log("Alert limits: " + (", ".join(f"{k}={v:g}" for k, v in custom.items()) or "defaults"))

        files.log("\n=== SUPPORTED COMMANDS (what this car reports) ===")
        files.log_lines(fmt_supported(conn))

        files.log("\n=== CAR INFO (start) ===")
        for name, value in self.static_start.items():
            files.log(f"  {name:<28} {value}")

        monitors = readers.read_monitors(conn, p.monitors)
        files.log("\n=== MODE 06 SELF-TESTS (start) ===")
        files.log_lines(fmt_monitors(monitors))

        self.state.misfire = readers.misfire_counts(monitors)
        self.state.misfire0 = self.state.misfire.get("total")
        self._apply_codes(readers.read_codes(conn))
        s = self.state
        log.info("MIL: %s | stored: %s | pending: %s", s.mil, s.stored or "none", s.pending or "none")
        files.log("\n=== CODES (start) ===")
        files.log(f"  MIL: {s.mil}  stored: {s.stored or 'none'}  pending: {s.pending or 'none'}")
        if s.stored:
            files.log("  Freeze frame:")
            files.log_lines(readers.freeze_frame(conn))

        self._poll(p.polled)  # first pass learns units, which name the CSV columns
        self.start_cool = self._reading("COOLANT_TEMP")
        self._columns = {c.name: column_name(c.name, self.units) for c in p.polled}
        files.start_csv(csv_fields([c.name for c in p.polled], self.units, list(s.misfire)))
        files.log("\n=== LIVE EVENTS ===")
        self._started = datetime.datetime.now().isoformat(timespec="seconds")
        self.sink.on_info(self._info())

    def _info(self) -> Dict[str, Any]:
        files = self._files()
        return {
            "car": self.car.to_dict(), "thresholds": asdict(self.limits),
            "port": self.port, "baud": self.baud, "protocol": self.conn.protocol_name(),
            "csv": str(files.csv_path), "report": str(files.report_path),
            "static": {k: str(v) for k, v in self.static_start.items()},
            "units": dict(self.units), "misfire0": self.state.misfire0,
            "sensors": [{"name": c.name, "desc": c.desc, "fast": c in self.plan.fast} for c in self.plan.polled],
        }  # fmt: skip

    # ---- main loop -------------------------------------------------------------
    def _loop(self) -> None:
        self._t0 = self._clock()
        last_slow = self._t0
        while not self.stop.is_set():
            tick = self._clock()
            got = self._poll_cycle()
            if not self._link_ok(got):
                break
            self._update_state()
            self._poll_lookup()
            if self._clock() - last_slow >= self.tune.slow_every:
                last_slow = self._clock()
                self._slow_checks()
            alerts = self._check_alerts()
            row = self._record(alerts)
            self.sink.on_row(row)
            self.stop.wait(max(0.0, self.tune.target_loop - (self._clock() - tick)))

    def _poll_cycle(self) -> int:
        p = self.plan
        got = self._poll(p.fast)
        if p.rest:
            n = min(self.tune.extra_per_loop, len(p.rest))
            got += self._poll([p.rest[(self._rotate + i) % len(p.rest)] for i in range(n)])
            self._rotate = (self._rotate + self.tune.extra_per_loop) % len(p.rest)
        volts = self.readings.get("CONTROL_MODULE_VOLTAGE")
        if volts is None:  # fall back to the adapter's own voltage reading
            volts = readers.parse_value(C.ELM_VOLTAGE, readers.query(self.conn, C.ELM_VOLTAGE))[0]
        self.readings["battery_v"] = volts
        return got

    def _poll(self, cmds: List[Any]) -> int:
        got = 0
        for cmd in cmds:
            value, unit = readers.parse_value(cmd, readers.query(self.conn, cmd))
            if unit:
                self.units[cmd.name] = unit
            self.readings[cmd.name] = value
            if isinstance(value, float):
                self.stats.setdefault(cmd.name, Stat()).add(value)
            got += value is not None
        return got

    def _link_ok(self, got: int) -> bool:
        """False when the link is gone for good (caller then finishes the session)."""
        self._empty = 0 if got else self._empty + 1
        if self._empty < self.tune.lost_after:
            return True
        msg = "No data from the car - engine off or link lost. Reconnecting..."
        log.warning(msg)
        self.sink.on_status("lost", msg)
        self.conn.close()
        self.conn = None
        for _ in range(self.tune.reconnect_tries):
            if self.stop.wait(self.tune.reconnect_wait):
                return False
            self.conn = self._connector(self.port, self.baud)
            if self.conn is not None:
                self.sink.on_status("connected", f"Reconnected on {self.port}")
                self._empty = 0
                return True
        log.error("Could not reconnect. Finishing up.")
        return False

    def _update_state(self) -> None:
        now, st = self._clock(), self.state
        rpm, spd, cool = self._reading("RPM"), self._reading("SPEED"), self._reading("COOLANT_TEMP")
        if rpm is not None and rpm > self.limits.running_rpm and st.run_start is None:
            st.run_start = now
        if spd is not None and spd > DRIVING_KPH:
            st.drove = True
        stft = self.readings.get("SHORT_FUEL_TRIM_1")
        if isinstance(stft, float):
            st.stft.append(stft)
        if cool is not None:
            for threshold in WARM_CHECKPOINTS_C:
                if cool >= threshold:
                    self.warm.setdefault(threshold, now - self._t0)

    def _slow_checks(self) -> None:
        """Trouble codes + misfire counters; a new stored code also gets a freeze-frame dump."""
        before = list(self.state.stored)
        self._apply_codes(readers.read_codes(self.conn))
        misfire_cmds = [c for c in self.plan.monitors if c.name.startswith("MONITOR_MISFIRE")]
        counts = readers.misfire_counts(readers.read_monitors(self.conn, misfire_cmds))
        self.state.misfire = counts or self.state.misfire
        fresh = [c for c in self.state.stored if c not in before]
        if fresh:
            files = self._files()
            files.log(f"  Freeze frame for new code(s) {fresh}:")
            files.log_lines(readers.freeze_frame(self.conn))

    def _apply_codes(self, codes: Codes) -> None:
        self.state.mil, self.state.stored, self.state.pending = codes["mil"], codes["stored"], codes["pending"]

    def _check_alerts(self) -> Dict[str, Alert]:
        """Raise an event when a problem first appears or gets worse; clear it silently."""
        now_active = evaluate(self.readings, self.state, self._clock(), self.limits)
        for topic, alert in now_active.items():
            previous = self.active.get(topic)
            if previous is None or previous.level != alert.level:
                self._raise(alert)
            self.worst = max(self.worst, LEVEL_RANK[alert.level])
        self.active = now_active
        return now_active

    def _raise(self, alert: Alert) -> None:
        stamp = f"{datetime.datetime.now():%H:%M:%S}"
        line = f"{stamp} [{alert.level}] {alert.msg}"
        log.warning(line)
        self._files().log(line)
        self.raised.append(f"[{alert.level}] {alert.msg}")
        self.sink.on_event({"time": stamp, "level": alert.level, "msg": alert.msg})
        self._notify(alert.level)

    def _record(self, alerts: Dict[str, Alert]) -> RowPayload:
        r, st = self.readings, self.state
        elapsed = self._clock() - self._t0
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cool, spd = self._reading("COOLANT_TEMP"), self._reading("SPEED")
        short, long_ = self._reading("SHORT_FUEL_TRIM_1"), self._reading("LONG_FUEL_TRIM_1")
        row: Dict[str, Any] = {"time": now, "elapsed_s": round(elapsed, 1)}
        row.update({col: r.get(name) for name, col in self._columns.items()})
        row.update(
            battery_v=r.get("battery_v"),
            coolant_f=round(cool * 9 / 5 + 32, 1) if cool is not None else None,
            speed_mph=round(spd * KPH_TO_MPH, 1) if spd is not None else None,
            trim_total_pct=round(short + long_, 2) if short is not None and long_ is not None else None,
            mil=st.mil, dtc_stored=len(st.stored), dtc_pending=len(st.pending),
        )  # fmt: skip
        row.update({f"misfire_{k}_cur": v for k, v in st.misfire.items()})
        self._files().write_row(row)
        self.loops += 1
        return {
            "t": round(elapsed, 1), "ts": now, "values": dict(r),
            "alerts": {k: list(a) for k, a in alerts.items()},
            "codes": {"mil": st.mil, "stored": list(st.stored), "pending": list(st.pending)},
            "misfire": dict(st.misfire), "misfire0": st.misfire0,
            "warm": {str(k): round(v, 1) for k, v in self.warm.items()}, "start_cool": self.start_cool,
        }  # fmt: skip

    # ---- wrap-up -----------------------------------------------------------------
    def _finish(self) -> None:
        files, st = self._files(), self.state
        end_codes: Dict[str, Any] = {"stored": [], "pending": [], "mil": None}
        monitors_end: Dict[str, Any] = {}
        static_end: Dict[str, Any] = {}
        if self.conn is not None:
            end_codes = dict(readers.read_codes(self.conn))
            monitors_end = readers.read_monitors(self.conn, self.plan.monitors)
            static_end = readers.read_counters(self.conn, self.plan.statics)

        failures = [f"{n}: {d}" for n, tests in monitors_end.items() for d, _, ok in tests if not ok]
        summary = render_summary(SummaryData(
            worst=self.worst, duration_s=self._clock() - self._t0, loops=self.loops,
            start_cool=self.start_cool, warm=self.warm, end_codes=end_codes,
            misfire_start=st.misfire0,
            misfire_end=readers.misfire_counts(monitors_end).get("total", st.misfire.get("total")),
            monitor_failures=failures, alerts_raised=self.raised,
            sensors=[c.name for c in self.plan.polled], units=self.units, stats=self.stats,
            static_start=self.static_start, static_end=static_end,
        ))  # fmt: skip
        files.log_lines(summary)
        files.write_summary(
            {
                "stamp": files.stamp, "app_version": __version__, "vin": self.car.vin, "car": self.car.title,
                "started": self._started, "duration_s": round(self._clock() - self._t0, 1), "rows": self.loops,
                "verdict": VERDICTS[self.worst], "alerts": len(self.raised), "alert_list": self.raised[:50],
                "start_coolant_c": self.start_cool, "warm_s": {str(k): round(v, 1) for k, v in self.warm.items()},
                "port": self.port, "baud": self.baud, "stored_codes": end_codes.get("stored", []),
                "misfire_total_end": readers.misfire_counts(monitors_end).get("total", st.misfire.get("total")),
                "distance_km": {k: _num(v) for k, v in static_end.items() if k.startswith("DISTANCE")},
            }
        )  # fmt: skip
        files.log("\n=== MODE 06 SELF-TESTS (end) ===")
        files.log_lines(fmt_monitors(monitors_end))
        log.info("Saved %s and %s", files.csv_path, files.report_path)
        self.sink.on_status(
            "finished", "Session finished",
            {"csv": str(files.csv_path), "report": str(files.report_path), "summary": summary},
        )  # fmt: skip

    # ---- helpers -------------------------------------------------------------------
    def _reading(self, key: str) -> Optional[float]:
        v = self.readings.get(key)
        return v if isinstance(v, (int, float)) else None

    def _files(self) -> SessionFiles:
        if self.files is None:
            raise RuntimeError("session files are not open")
        return self.files


def _num(value: Any) -> Optional[float]:
    magnitude = getattr(value, "magnitude", value)
    return round(float(magnitude), 1) if isinstance(magnitude, (int, float)) else None
