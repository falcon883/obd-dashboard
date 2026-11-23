from __future__ import annotations

import json
import re
from dataclasses import asdict, fields
from pathlib import Path

import pytest

from obd_dashboard.rules import RuleState, evaluate
from obd_dashboard.userconfig import (
    ADVANCED_DEFAULTS,
    ADVANCED_FIELDS,
    DEFAULT_THRESHOLDS,
    ORDERED,
    THRESHOLD_FIELDS,
    ConfigError,
    Thresholds,
    UserConfig,
)

VIN = "5NPE24AF3GH283081"


@pytest.fixture
def config(tmp_path):
    return UserConfig(tmp_path / "logs")


def stored(config):
    return json.loads(config.path.read_text(encoding="utf-8"))


# ---- the field table and the dataclass must describe the same things -----------------------------
def test_field_table_matches_thresholds_dataclass():
    assert {f.key for f in THRESHOLD_FIELDS} == {f.name for f in fields(Thresholds)}
    for f in THRESHOLD_FIELDS:
        assert getattr(DEFAULT_THRESHOLDS, f.key) == f.default, f.key


def test_advanced_table_matches_defaults():
    assert {f.key for f in ADVANCED_FIELDS} == set(ADVANCED_DEFAULTS)
    assert all(ADVANCED_DEFAULTS[f.key] == f.default for f in ADVANCED_FIELDS)


def test_every_default_is_valid_and_in_range():
    for f in THRESHOLD_FIELDS + ADVANCED_FIELDS:
        assert f.parse(f.default) == f.default, f.key
    for lo, hi in ORDERED:
        assert getattr(DEFAULT_THRESHOLDS, lo) < getattr(DEFAULT_THRESHOLDS, hi)


def test_frontend_fallback_limits_match_the_backend_defaults():
    """format.js keeps a copy of the defaults for the instant before a session reports its own."""
    source = (Path(__file__).parent.parent / "frontend" / "src" / "format.js").read_text(encoding="utf-8")
    block = re.search(r"DEFAULT_LIMITS = \{(.*?)\n\}", source, re.S)
    assert block, "DEFAULT_LIMITS not found in frontend/src/format.js"
    js = {k: float(v) for k, v in re.findall(r"(\w+):\s*(-?[\d.]+)", block.group(1))}
    assert js == {k: float(v) for k, v in asdict(DEFAULT_THRESHOLDS).items()}


# ---- reading ---------------------------------------------------------------------------------
def test_defaults_when_there_is_no_file(config):
    assert config.thresholds() == DEFAULT_THRESHOLDS
    assert config.advanced() == ADVANCED_DEFAULTS and config.advanced_overrides() == {}
    assert not config.path.exists()  # reading never creates files


def test_corrupt_or_hand_broken_file_never_crashes_a_session(config):
    config.path.parent.mkdir(parents=True)
    config.path.write_text("{not json", encoding="utf-8")
    assert config.thresholds() == DEFAULT_THRESHOLDS
    config.path.write_text(
        json.dumps(
            {"thresholds": {"coolant_warn_c": 99, "coolant_crit_c": "hot", "bogus": 1}, "cars": [], "advanced": 5}
        ),
        encoding="utf-8",
    )
    t = config.thresholds()
    assert t.coolant_warn_c == 99 and t.coolant_crit_c == DEFAULT_THRESHOLDS.coolant_crit_c
    assert config.advanced() == ADVANCED_DEFAULTS


# ---- saving ----------------------------------------------------------------------------------
def test_only_changes_are_stored_and_defaults_drop_out(config):
    config.set_thresholds({"coolant_warn_c": 100, "coolant_crit_c": 108, "fuel_low_pct": 15})
    assert stored(config)["thresholds"] == {"coolant_warn_c": 100, "fuel_low_pct": 15}
    assert config.thresholds().coolant_warn_c == 100 and config.thresholds().fuel_low_pct == 15
    config.set_thresholds({"coolant_warn_c": 102})  # back to the default: nothing left to store
    assert stored(config)["thresholds"] == {}


def test_a_car_can_have_its_own_limits_on_top_of_the_global_ones(config):
    config.set_thresholds({"coolant_warn_c": 100})
    config.set_thresholds({"catalyst_warn_c": 900, "catalyst_crit_c": 950}, VIN)
    mine, other = config.thresholds(VIN), config.thresholds("1M8GDM9AXKP042781")
    assert mine.coolant_warn_c == 100 and mine.catalyst_warn_c == 900  # global edit + own edit
    assert other.coolant_warn_c == 100 and other.catalyst_warn_c == DEFAULT_THRESHOLDS.catalyst_warn_c
    config.set_thresholds({"coolant_warn_c": 100}, VIN)  # same as the global value: not an override
    assert stored(config)["cars"] == {}


def test_advanced_changes_are_sparse(config):
    config.set_advanced({"beep": False, "target_loop": 1.0, "slow_every": 30})
    assert config.advanced_overrides() == {"beep": False, "slow_every": 30}
    assert config.advanced()["target_loop"] == 1.0 and config.advanced()["beep"] is False


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"nope": 1}, "Unknown setting 'nope'"),
        ({"coolant_warn_c": 500}, "must be between"),
        ({"coolant_warn_c": "hot"}, "must be a number"),
        ({"coolant_warn_c": True}, "must be a number"),
        ({"coolant_warn_c": float("nan")}, "must be a number"),
        ({"running_rpm": 400.5}, "whole number"),
        ({"coolant_warn_c": 110}, "must be below"),  # above the critical limit
        ({"idle_rpm_min": 1000, "idle_rpm_max": 800}, "must be below"),
    ],
)
def test_bad_values_are_refused_with_a_reason(config, values, message):
    with pytest.raises(ConfigError) as err:
        config.set_thresholds(values)
    assert message in str(err.value)
    assert not config.path.exists()  # nothing half-saved


def test_every_problem_is_reported_at_once(config):
    with pytest.raises(ConfigError) as err:
        config.set_thresholds({"coolant_warn_c": 500, "fuel_low_pct": "x", "zzz": 1})
    assert len(err.value.problems) == 3


def test_advanced_checks_types(config):
    with pytest.raises(ConfigError):
        config.set_advanced({"beep": "yes"})
    with pytest.raises(ConfigError):
        config.set_advanced({"target_loop": 0})
    with pytest.raises(ConfigError):
        config.set_advanced({"coolant_warn_c": 100})  # a limit, not an advanced option


def test_reset_scopes(config):
    config.set_thresholds({"fuel_low_pct": 15})
    config.set_thresholds({"fuel_low_pct": 20}, VIN)
    config.set_advanced({"beep": False})
    config.reset("thresholds", VIN)
    assert config.thresholds(VIN).fuel_low_pct == 15
    config.reset("thresholds")
    assert config.thresholds().fuel_low_pct == DEFAULT_THRESHOLDS.fuel_low_pct and config.advanced()["beep"] is False
    config.reset("advanced")
    assert config.advanced() == ADVANCED_DEFAULTS
    config.set_thresholds({"fuel_low_pct": 15})
    config.reset("all")
    assert stored(config) == {"thresholds": {}, "advanced": {}, "cars": {}}
    with pytest.raises(ConfigError):
        config.reset("everything")


def test_snapshot_has_what_the_screen_needs(config):
    config.set_thresholds({"fuel_low_pct": 15}, VIN)
    snap = config.snapshot([{"vin": VIN, "name": "2016 Hyundai Sonata"}])
    assert snap["defaults"] == asdict(DEFAULT_THRESHOLDS) and snap["thresholds"] == snap["defaults"]
    assert snap["cars"] == [{"vin": VIN, "name": "2016 Hyundai Sonata", "overrides": {"fuel_low_pct": 15}}]
    assert {f["key"] for f in snap["schema"]["thresholds"]} == {f.key for f in THRESHOLD_FIELDS}
    json.dumps(snap)  # must be plain JSON


# ---- the rules really use the configured limits -------------------------------------------------
def test_rules_follow_custom_limits():
    stricter = Thresholds(coolant_warn_c=95, coolant_crit_c=100)
    assert evaluate({"COOLANT_TEMP": 97.0}, RuleState(), 0.0) == {}
    assert evaluate({"COOLANT_TEMP": 97.0}, RuleState(), 0.0, stricter)["coolant"].level == "WARN"
    assert evaluate({"COOLANT_TEMP": 101.0}, RuleState(), 0.0, stricter)["coolant"].level == "CRIT"


def test_each_limit_changes_the_rule_it_belongs_to():
    t = Thresholds(
        catalyst_warn_c=1100, catalyst_crit_c=1200, fuel_low_pct=50, misfire_rise=2, ltft_warn_pct=5, running_rpm=900
    )
    assert evaluate({"CATALYST_TEMP_B1S1": 980.0}, RuleState(), 0.0) != {}
    assert evaluate({"CATALYST_TEMP_B1S1": 980.0}, RuleState(), 0.0, t) == {}
    assert "fuel" in evaluate({"FUEL_LEVEL": 40.0}, RuleState(), 0.0, t)
    assert "misfire" in evaluate({}, RuleState(misfire0=1.0, misfire={"total": 3.0}), 0.0, t)
    assert "ltft" in evaluate({"LONG_FUEL_TRIM_1": 6.0}, RuleState(), 0.0, t)
    low_charge = {"RPM": 700.0, "battery_v": 12.5}
    default_state, custom_state = RuleState(), RuleState()
    evaluate(low_charge, default_state, 0.0)
    evaluate(low_charge, custom_state, 0.0, t)
    assert "battery" in evaluate(low_charge, default_state, 10.0)  # 700 rpm counts as running by default
    assert "battery" not in evaluate(low_charge, custom_state, 10.0, t)  # ...but not with running_rpm=900


def test_thermostat_check_uses_the_configured_minutes():
    state = RuleState(drove=True, run_start=0.0)
    t = Thresholds(warmup_check_after_min=5)
    assert "warmup" in evaluate({"COOLANT_TEMP": 75.0}, state, 400.0, t)
    assert "warmup" not in evaluate({"COOLANT_TEMP": 75.0}, state, 400.0)


def test_trim_average_window_comes_from_the_limits():
    t = Thresholds(stft_window=5)
    state = RuleState.for_limits(t)
    assert state.stft.maxlen == 5
    state.stft.extend([20.0] * 5)
    assert "stft" in evaluate({}, state, 0.0, t)
