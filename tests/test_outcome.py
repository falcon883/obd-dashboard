"""The end-of-drive card: totals over one drive, the same dictionary from a real session and the demo."""

from __future__ import annotations

import threading
from dataclasses import replace

from obd_dashboard.demo import run_demo
from obd_dashboard.outcome import DriveTally
from tests.conftest import RecordingSink
from tests.fakes import FakeCar
from tests.test_session import run_session


def test_distance_adds_up_speed_over_time_and_ignores_long_gaps() -> None:
    tally = DriveTally()
    for second in range(0, 61):  # one minute at 60 km/h = 1 km
        tally.add(float(second), speed_kph=60.0)
    tally.add(500.0, speed_kph=60.0)  # a link drop: the car was not measured for minutes
    assert round(tally.distance_km, 2) == 1.0


def test_voltage_and_trim_averages_only_count_a_running_engine() -> None:
    tally = DriveTally()
    tally.add(0.0, rpm=0.0, volts=12.4, ltft_pct=5.0)  # key on, engine off
    tally.add(1.0, rpm=800.0, volts=0.0, ltft_pct=2.0)  # the computer winding down: not a battery reading
    tally.add(2.0, rpm=800.0, volts=14.2, ltft_pct=2.0)
    tally.add(3.0, rpm=800.0, volts=14.4, ltft_pct=4.0)
    result = tally.outcome(
        verdict="ok", duration_s=3, rows=4, start_coolant_c=40, warm_s={}, alerts=[], stored=[], pending=[], mil=False
    )
    assert result["battery_avg_v"] == 14.3 and result["ltft_avg_pct"] == 2.67


def test_nothing_measured_gives_blanks_not_zeros() -> None:
    result = DriveTally().outcome(
        verdict="ok", duration_s=0, rows=0, start_coolant_c=None, warm_s={}, alerts=[], stored=[], pending=[], mil=None
    )
    assert result["battery_avg_v"] is None and result["coolant_max_c"] is None and result["rows_per_s"] is None


def test_hottest_coolant_is_kept() -> None:
    tally = DriveTally()
    for t, c in enumerate([40.0, 95.0, 88.0]):
        tally.add(float(t), coolant_c=c)
    assert tally.coolant_max == 95.0


def test_a_real_session_ends_with_the_card_numbers(settings) -> None:
    session, sink = run_session(replace(settings, com="FAKE0", baud=38400), FakeCar(), rows=30)
    outcome = sink.statuses[-1][2]["outcome"]
    assert outcome["verdict"] == "crit" and outcome["rows"] == 30 and outcome["demo"] is False
    assert outcome["coolant_max_c"] > 102 and outcome["stored"] == ["P0300 Random misfire"]
    assert any("Coolant running hot" in a for a in outcome["alerts"])


def test_the_demo_ends_with_the_same_kind_of_card() -> None:
    stop = threading.Event()
    sink = RecordingSink(stop, 120)
    run_demo(sink, stop, tick=0.0)
    outcome = sink.statuses[-1][2]["outcome"]
    assert outcome["demo"] is True and outcome["rows"] == 120 and outcome["distance_km"] > 0
    assert outcome["verdict"] == "warn" and len(outcome["alerts"]) == 1
