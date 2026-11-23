"""A simulated car for trying the dashboard without hardware. Clearly labelled DEMO in the UI."""

from __future__ import annotations

import datetime
import math
import random
import threading
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from obd_dashboard.outcome import DriveTally
from obd_dashboard.types import Sink
from obd_dashboard.userconfig import DEFAULT_THRESHOLDS, Thresholds

# (name, description, unit, polled every loop)
DEMO_SENSORS: List[Tuple[str, str, Optional[str], bool]] = [
    ("RPM", "Engine RPM", "revolutions_per_minute", True),
    ("SPEED", "Vehicle Speed", "kilometer_per_hour", True),
    ("ENGINE_LOAD", "Calculated Engine Load", "percent", True),
    ("COOLANT_TEMP", "Engine Coolant Temperature", "degree_Celsius", True),
    ("THROTTLE_POS", "Throttle Position", "percent", True),
    ("SHORT_FUEL_TRIM_1", "Short Term Fuel Trim - Bank 1", "percent", True),
    ("LONG_FUEL_TRIM_1", "Long Term Fuel Trim - Bank 1", "percent", True),
    ("INTAKE_PRESSURE", "Intake Manifold Pressure", "kilopascal", True),
    ("TIMING_ADVANCE", "Timing Advance", "degree", True),
    ("CONTROL_MODULE_VOLTAGE", "Control module voltage", "volt", True),
    ("FUEL_STATUS", "Fuel System Status", None, False),
    ("INTAKE_TEMP", "Intake Air Temp", "degree_Celsius", False),
    ("O2_B1S2", "O2: Bank 1 - Sensor 2 Voltage", "volt", False),
    ("RUN_TIME", "Engine Run Time", "second", False),
    ("EVAPORATIVE_PURGE", "Commanded Evaporative Purge", "percent", False),
    ("FUEL_LEVEL", "Fuel Level Input", "percent", False),
    ("BAROMETRIC_PRESSURE", "Barometric Pressure", "kilopascal", False),
    ("CATALYST_TEMP_B1S1", "Catalyst Temperature: Bank 1 - Sensor 1", "degree_Celsius", False),
    ("CATALYST_TEMP_B1S2", "Catalyst Temperature: Bank 1 - Sensor 2", "degree_Celsius", False),
    ("ABSOLUTE_LOAD", "Absolute load value", "percent", False),
    ("COMMANDED_EQUIV_RATIO", "Commanded equivalence ratio", "ratio", False),
    ("RELATIVE_THROTTLE_POS", "Relative throttle position", "percent", False),
    ("AMBIANT_AIR_TEMP", "Ambient air temperature", "degree_Celsius", False),
    ("ACCELERATOR_POS_D", "Accelerator pedal position D", "percent", False),
    ("FUEL_RAIL_PRESSURE_ABS", "Fuel rail pressure (absolute)", "kilopascal", False),
]  # fmt: skip

DEMO_CAR = {
    "vin": "DEMO", "year": 2016, "make": "Hyundai", "model": "Sonata", "trim": None, "engine": "2.4 L 4-cyl",
    "nickname": "", "source": "demo", "title": "2016 Hyundai Sonata", "display_name": "2016 Hyundai Sonata",
}  # fmt: skip
DRILL_WINDOW_S = (90, 100)
DRILL_MESSAGE = "Demo alert - simulated warning (this is a drill)"
WARM_CHECKPOINTS_C = (70, 80, 85)


def _rpm_for(speed: float, accel: float, rng: random.Random) -> float:
    if speed < 1:
        rpm = 760 + rng.gauss(0, 12)
    elif speed < 15:
        rpm = 800 + speed * 100
    elif speed < 30:
        rpm = 1400 + (speed - 15) * 60
    elif speed < 45:
        rpm = 1600 + (speed - 30) * 50
    elif speed < 60:
        rpm = 1700 + (speed - 45) * 45
    else:
        rpm = 1900 + (speed - 60) * 40
    return rpm + max(0, accel) * 25 + rng.gauss(0, 10)


class DemoCar:
    """Idle warm-up, then a repeating stop-and-go drive. Deterministic for a given seed."""

    def __init__(self, seed: int = 7) -> None:
        self.rng = random.Random(seed)
        self.speed = 0.0
        self.coolant = 48.0
        self.ltft = 3.1
        self.fuel = 62.0
        self.cat1, self.cat2 = 120.0, 100.0
        self.misfire: Dict[str, float] = {"total": 3.0, "cyl1": 0.0, "cyl2": 2.0, "cyl3": 0.0, "cyl4": 1.0}
        self.warm: Dict[str, float] = {}
        self.start_cool = self.coolant

    def step(self, t: float) -> Dict[str, Any]:
        rng = self.rng
        prev = self.speed
        u = (t - 25) % 120
        self.speed = 0.0 if t < 25 or u > 100 else 72 * math.sin(math.pi * u / 100) ** 1.4
        speed, accel = self.speed, self.speed - prev
        rpm = _rpm_for(speed, accel, rng)
        load = 17 + speed * 0.28 + max(0, accel) * 3.5 + rng.gauss(0, 0.4)
        throttle = 12.5 + max(0, accel) * 2.6 + speed * 0.12 + rng.gauss(0, 0.1)
        self.coolant = min(93.5, self.coolant + ((92 if speed > 0 else 82) - self.coolant) / 140 + rng.gauss(0, 0.05))
        self.ltft = min(4.5, max(2.0, self.ltft + rng.gauss(0, 0.02)))
        self.fuel = max(5.0, self.fuel - 0.0015 * (1 + speed / 40))
        self.cat1 += ((300 + load * 8) - self.cat1) / 40
        self.cat2 += ((250 + load * 6) - self.cat2) / 60
        for th in WARM_CHECKPOINTS_C:
            if self.coolant >= th:
                self.warm.setdefault(str(th), round(t, 1))
        if rng.random() < 0.004:
            self.misfire[rng.choice(["cyl1", "cyl2", "cyl3", "cyl4"])] += 1
            self.misfire["total"] += 1
        volts = round(14.28 + rng.gauss(0, 0.07), 2)
        return {
            "RPM": round(rpm), "SPEED": round(speed, 1), "ENGINE_LOAD": round(load, 1),
            "COOLANT_TEMP": round(self.coolant), "THROTTLE_POS": round(throttle, 1),
            "SHORT_FUEL_TRIM_1": round(2.0 * math.sin(t / 3) + rng.gauss(0, 0.4), 2),
            "LONG_FUEL_TRIM_1": round(self.ltft, 2), "INTAKE_PRESSURE": round(33 + load * 0.55),
            "TIMING_ADVANCE": round(5 + load * 0.3 + rng.gauss(0, 1.2), 1),
            "CONTROL_MODULE_VOLTAGE": volts, "battery_v": volts,
            "FUEL_STATUS": "open_loop_cold" if self.coolant < 60 else "closed_loop",
            "INTAKE_TEMP": round(28 + min(12.0, t / 60)), "O2_B1S2": round(0.62 + 0.1 * math.sin(t / 7), 2),
            "RUN_TIME": round(t), "EVAPORATIVE_PURGE": 0.0, "FUEL_LEVEL": round(self.fuel, 1),
            "BAROMETRIC_PRESSURE": 99, "CATALYST_TEMP_B1S1": round(self.cat1, 1),
            "CATALYST_TEMP_B1S2": round(self.cat2, 1), "ABSOLUTE_LOAD": round(load * 1.18, 1),
            "COMMANDED_EQUIV_RATIO": round(1 + rng.gauss(0, 0.0008), 4),
            "RELATIVE_THROTTLE_POS": round(max(0.0, throttle - 9), 1), "AMBIANT_AIR_TEMP": 13,
            "ACCELERATOR_POS_D": round(max(0.0, throttle - 8) * 1.1, 1),
            "FUEL_RAIL_PRESSURE_ABS": round(4800 + load * 40),
        }  # fmt: skip


def run_demo(
    sink: Sink, stop: threading.Event, tick: float = 1.0, seed: int = 7, limits: Thresholds = DEFAULT_THRESHOLDS
) -> None:
    sink.on_status("connected", "Demo mode - simulated car")
    sink.on_info({
        "car": DEMO_CAR, "thresholds": asdict(limits), "port": "DEMO", "baud": 0,
        "protocol": "Simulated (no hardware)", "csv": None, "report": None,
        "static": {"VIN": "DEMO-VIN-0000000", "FUEL_TYPE": "Gasoline", "WARMUPS_SINCE_DTC_CLEAR": "42"},
        "units": {n: u for n, _, u, _ in DEMO_SENSORS if u}, "misfire0": 3.0,
        "sensors": [{"name": n, "desc": d, "fast": f} for n, d, _, f in DEMO_SENSORS],
    })  # fmt: skip
    car, t, drill_sent, tally = DemoCar(seed), 0.0, False, DriveTally()
    loops = 0
    while not stop.is_set():
        values = car.step(t)
        alerts: Dict[str, List[str]] = {}
        if DRILL_WINDOW_S[0] <= t < DRILL_WINDOW_S[1]:  # one fake warning so the alert UI is visible
            alerts["demo"] = ["WARN", DRILL_MESSAGE]
            if not drill_sent:
                drill_sent = True
                sink.on_event({"time": f"{datetime.datetime.now():%H:%M:%S}", "level": "WARN", "msg": DRILL_MESSAGE})
        sink.on_row({
            "t": round(t, 1), "ts": f"{datetime.datetime.now():%Y-%m-%dT%H:%M:%S}", "values": values,
            "alerts": alerts, "codes": {"mil": False, "stored": [], "pending": []},
            "misfire": dict(car.misfire), "misfire0": 3.0, "warm": dict(car.warm),
            "start_cool": car.start_cool,
        })  # fmt: skip
        tally.add(
            t, speed_kph=values.get("SPEED"), coolant_c=values.get("COOLANT_TEMP"), rpm=values.get("RPM"),
            volts=values.get("battery_v"), ltft_pct=values.get("LONG_FUEL_TRIM_1"),
        )  # fmt: skip
        loops += 1
        t += 1.0
        stop.wait(tick)
    sink.on_status(
        "finished", "Session finished",
        {
            "csv": None, "report": None, "summary": ["Demo session ended."],
            "outcome": tally.outcome(
                verdict="warn" if t > DRILL_WINDOW_S[0] else "ok", duration_s=t, rows=loops,
                start_coolant_c=car.start_cool, warm_s={k: float(v) for k, v in car.warm.items()},
                alerts=[DRILL_MESSAGE] if drill_sent else [], stored=[], pending=[], mil=False, demo=True,
            ),
        },
    )  # fmt: skip
