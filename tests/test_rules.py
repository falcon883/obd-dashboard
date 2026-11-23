from __future__ import annotations

import pytest

from obd_dashboard.rules import BATTERY_SUSTAIN_S, RuleState, evaluate


def run(readings, state=None, now=0.0):
    return evaluate(readings, state or RuleState(), now)


def test_healthy_car_has_no_alerts():
    r = {
        "RPM": 750.0,
        "SPEED": 0.0,
        "COOLANT_TEMP": 90.0,
        "battery_v": 14.3,
        "LONG_FUEL_TRIM_1": 3.0,
        "FUEL_LEVEL": 40.0,
    }
    assert run(r) == {}


@pytest.mark.parametrize(("temp", "level"), [(101, None), (102, "WARN"), (107, "WARN"), (108, "CRIT")])
def test_coolant_thresholds(temp, level):
    alerts = run({"COOLANT_TEMP": float(temp)})
    assert (alerts["coolant"].level if "coolant" in alerts else None) == level


def test_warmup_alert_needs_driving_and_20_minutes():
    state = RuleState(drove=True, run_start=0.0)
    assert "warmup" not in run({"COOLANT_TEMP": 75.0}, state, now=600)
    assert run({"COOLANT_TEMP": 75.0}, state, now=1300)["warmup"].level == "WARN"
    assert "warmup" not in run({"COOLANT_TEMP": 90.0}, state, now=1300)
    assert "warmup" not in run({"COOLANT_TEMP": 75.0}, RuleState(drove=False, run_start=0.0), now=1300)


@pytest.mark.parametrize(
    ("rpm", "volts", "expected"),
    [
        (800.0, 12.5, "Charging low"),
        (800.0, 15.4, "Overcharging"),
        (0.0, 11.5, "Weak battery"),
        (800.0, 14.2, None),
        (0.0, 12.4, None),
    ],
)
def test_battery(rpm, volts, expected):
    state = RuleState()
    readings = {"RPM": rpm, "battery_v": volts}
    run(readings, state, now=0.0)
    alerts = run(readings, state, now=BATTERY_SUSTAIN_S)
    if expected is None:
        assert "battery" not in alerts
    else:
        assert expected in alerts["battery"].msg


def test_battery_alert_waits_until_the_problem_lasts():
    """Real logs: 12.1 V in the first second after start and 11.0 V while cranking were not faults."""
    state = RuleState()
    sag = {"RPM": 1286.0, "battery_v": 12.1}
    assert "battery" not in run(sag, state, now=0.0)
    assert "battery" not in run(sag, state, now=BATTERY_SUSTAIN_S - 0.1)
    assert "battery" in run(sag, state, now=BATTERY_SUSTAIN_S)


def test_battery_dip_that_recovers_never_alerts_and_restarts_the_clock():
    state = RuleState()
    assert "battery" not in run({"RPM": 0.0, "battery_v": 11.0}, state, now=0.0)  # cranking
    assert "battery" not in run({"RPM": 1441.0, "battery_v": 14.9}, state, now=1.0)  # running, charging
    assert "battery" not in run({"RPM": 1441.0, "battery_v": 12.1}, state, now=2.0)  # a new problem starts here
    assert "battery" not in run({"RPM": 1441.0, "battery_v": 12.1}, state, now=2.0 + BATTERY_SUSTAIN_S - 0.1)


def test_a_different_battery_problem_restarts_the_clock():
    state = RuleState()
    run({"RPM": 800.0, "battery_v": 12.5}, state, now=0.0)  # charging low
    assert "battery" not in run({"RPM": 800.0, "battery_v": 15.4}, state, now=BATTERY_SUSTAIN_S)  # now overcharging
    assert "Overcharging" in run({"RPM": 800.0, "battery_v": 15.4}, state, now=2 * BATTERY_SUSTAIN_S)["battery"].msg


def test_long_term_fuel_trim_direction_and_severity():
    lean = run({"LONG_FUEL_TRIM_1": 12.0})["ltft"]
    rich = run({"LONG_FUEL_TRIM_1": -25.0})["ltft"]
    assert lean.level == "WARN" and "lean" in lean.msg
    assert rich.level == "CRIT" and "rich" in rich.msg
    assert "ltft" not in run({"LONG_FUEL_TRIM_1": 9.9})


def test_short_term_trim_needs_a_full_window():
    state = RuleState()
    state.stft.extend([20.0] * 29)
    assert "stft" not in run({}, state)
    state.stft.append(20.0)
    assert run({}, state)["stft"].level == "WARN"


def test_idle_rule_only_when_warm_and_stopped():
    assert "idle" in run({"RPM": 1500.0, "SPEED": 0.0, "COOLANT_TEMP": 90.0})
    assert "idle" not in run({"RPM": 1500.0, "SPEED": 30.0, "COOLANT_TEMP": 90.0})
    assert "idle" not in run({"RPM": 1500.0, "SPEED": 0.0, "COOLANT_TEMP": 50.0})
    assert "idle" not in run({"RPM": 750.0, "SPEED": 0.0, "COOLANT_TEMP": 90.0})


def test_catalyst_alerts_only_above_normal_full_load_temperatures():
    # A real 25-minute drive peaked at 934C on hard acceleration and 111 km/h: that is normal, not an alert.
    assert "cat" not in run({"CATALYST_TEMP_B1S1": 934.0, "CATALYST_TEMP_B1S2": 863.0})
    assert run({"CATALYST_TEMP_B1S1": 700.0, "CATALYST_TEMP_B1S2": 960.0})["cat"].level == "WARN"  # hottest sensor
    assert run({"CATALYST_TEMP_B1S2": 1010.0})["cat"].level == "CRIT"


def test_misfire_rise_is_measured_from_session_start():
    assert "misfire" not in run({}, RuleState(misfire0=3.0, misfire={"total": 12.0}))
    assert "misfire" in run({}, RuleState(misfire0=3.0, misfire={"total": 13.0}))
    assert "misfire" not in run({}, RuleState(misfire0=None, misfire={"total": 99.0}))


def test_codes_and_mil():
    alerts = run({}, RuleState(mil=True, stored=["P0300 Random misfire"], pending=["P0171 Lean"]))
    assert alerts["mil"].level == "CRIT"
    assert alerts["dtc"].level == "CRIT" and "P0300" in alerts["dtc"].msg
    assert alerts["pending"].level == "WARN"


def test_missing_and_non_numeric_readings_are_ignored():
    assert run({"COOLANT_TEMP": None, "RPM": "closed_loop", "battery_v": None, "FUEL_LEVEL": True}) == {}
