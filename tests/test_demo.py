from __future__ import annotations

import threading

from obd_dashboard.demo import DEMO_SENSORS, DemoCar, run_demo
from tests.conftest import RecordingSink


def test_demo_car_is_deterministic_and_plausible():
    a, b = DemoCar(seed=1), DemoCar(seed=1)
    first = [a.step(t) for t in range(0, 130, 5)]
    assert first == [b.step(t) for t in range(0, 130, 5)]
    assert first[0]["SPEED"] == 0 and max(v["SPEED"] for v in first) > 30
    assert all(600 < v["RPM"] < 4000 and 40 <= v["COOLANT_TEMP"] <= 94 for v in first)
    assert all(13.5 < v["battery_v"] < 15 for v in first)


def test_demo_values_cover_every_declared_sensor():
    values = DemoCar().step(10.0)
    assert {n for n, *_ in DEMO_SENSORS} <= set(values)


def test_run_demo_streams_rows_and_one_drill_alert():
    stop = threading.Event()
    sink = RecordingSink(stop, stop_after_rows=105)
    run_demo(sink, stop, tick=0.0)
    assert sink.states == ["connected", "finished"]
    assert len(sink.rows) == 105 and sink.infos[0]["port"] == "DEMO"
    assert len(sink.events) == 1 and "drill" in sink.events[0]["msg"]
    assert any(r["alerts"] for r in sink.rows) and not sink.rows[0]["alerts"]
