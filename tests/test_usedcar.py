from __future__ import annotations

from copy import deepcopy
from typing import Any

from obd_dashboard.demo import DEMO_CHECK_SNAPSHOT
from obd_dashboard.usedcar import CAVEAT, assess, render_report
from obd_dashboard.userconfig import DEFAULT_THRESHOLDS

CLEAN: dict[str, Any] = {
    "vin": "5NPE24AF3GH283081",
    "car": "2016 Hyundai Sonata",
    "codes": {"mil": False, "stored": [], "pending": []},
    "readiness": [
        {"name": "MISFIRE_MONITORING", "available": True, "complete": True},
        {"name": "CATALYST_MONITORING", "available": True, "complete": True},
        {"name": "EVAPORATIVE_SYSTEM_MONITORING", "available": True, "complete": True},
    ],
    "since_clear": {"distance_km": 5200.0, "warmups": 130.0, "minutes": 9000.0},
    "mil_km": None,
    "mil_minutes": None,
    "monitors_read": True,
    "monitors_failed": [],
    "misfire_total": 0.0,
    "idle": {
        "samples": 80, "running": True, "moving": False, "rpm_min": 740.0, "rpm_max": 770.0, "rpm_mean": 755.0,
        "ltft": 2.0, "stft": 1.0, "volts_off": 12.6, "volts_run": 14.2, "coolant_start": 88.0, "coolant_end": 90.0,
    },
}  # fmt: skip


def snap(**changes: Any) -> dict[str, Any]:
    out = deepcopy(CLEAN)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key].update(value)
        else:
            out[key] = value
    return out


def levels(result: dict[str, Any]) -> dict[str, str]:
    return {f["id"]: f["level"] for f in result["findings"]}


def test_clean_car_has_nothing_to_flag():
    result = assess(CLEAN)
    assert result["verdict"] == "clear" and result["headline"] == "Nothing worrying found"
    assert {f["level"] for f in result["findings"]} == {"ok"}
    assert result["caveat"] == CAVEAT


def test_check_engine_light_and_stored_codes_are_serious():
    result = assess(snap(codes={"mil": True, "stored": ["P0420"], "pending": []}))
    assert result["verdict"] == "flags"
    lv = levels(result)
    assert lv["mil"] == "bad" and lv["stored"] == "bad"
    assert "P0420" in next(f["title"] for f in result["findings"] if f["id"] == "stored")


def test_pending_codes_are_a_warning():
    result = assess(snap(codes={"mil": False, "stored": [], "pending": ["P0171"]}))
    assert levels(result)["pending"] == "warn" and result["verdict"] == "look"


def test_unreadable_codes_are_not_reported_as_clean():
    result = assess(snap(codes=None))
    assert levels(result)["codes"] == "info"


def test_recent_reset_is_a_warning():
    result = assess(snap(since_clear={"distance_km": 30.0}))
    assert levels(result)["cleared"] == "warn" and result["verdict"] == "look"


def test_recent_reset_with_unfinished_self_tests_is_the_classic_hidden_fault_sign():
    unfinished = [
        {"name": "CATALYST_MONITORING", "available": True, "complete": False},
        {"name": "EVAPORATIVE_SYSTEM_MONITORING", "available": True, "complete": False},
    ]
    result = assess(snap(since_clear={"distance_km": 30.0}, readiness=unfinished))
    assert result["verdict"] == "flags" and levels(result)["readiness"] == "bad"
    detail = next(f["detail"] for f in result["findings"] if f["id"] == "readiness")
    assert "catalyst" in detail and "evaporative system" in detail


def test_unfinished_self_tests_without_a_recent_reset_are_only_a_warning():
    unfinished = [{"name": f"T{i}_MONITORING", "available": True, "complete": False} for i in range(2)]
    assert levels(assess(snap(readiness=unfinished)))["readiness"] == "warn"
    assert levels(assess(snap(readiness=unfinished[:1])))["readiness"] == "info"


def test_tests_the_car_does_not_have_are_not_counted():
    absent = [{"name": "EGR_MONITORING", "available": False, "complete": False}] * 3
    assert levels(assess(snap(readiness=absent)))["readiness"] == "ok"


def test_moderately_recent_reset_is_just_a_note():
    assert levels(assess(snap(since_clear={"distance_km": 400.0})))["cleared"] == "info"


def test_warmups_stand_in_when_the_car_does_not_report_distance():
    result = assess(snap(since_clear={"distance_km": None, "warmups": 2.0}))
    assert levels(result)["cleared"] == "warn"
    assert levels(assess(snap(since_clear={"distance_km": None, "warmups": None})))["cleared"] == "info"


def test_light_history_is_reported():
    result = assess(snap(mil_km=320.0, mil_minutes=600.0))
    detail = next(f["detail"] for f in result["findings"] if f["id"] == "mil_history")
    assert levels(result)["mil_history"] == "warn" and "320 km" in detail and "10.0 hours" in detail


def test_failed_self_test_results_warn_but_never_condemn():
    result = assess(snap(monitors_failed=["evap 150: Unknown"] * 6))
    assert levels(result)["selftests"] == "warn" and result["verdict"] == "look"


def test_misfire_count_scales_with_size():
    assert levels(assess(snap(misfire_total=3.0)))["misfire"] == "info"
    assert levels(assess(snap(misfire_total=40.0)))["misfire"] == "warn"
    assert "misfire" not in levels(assess(snap(misfire_total=0.0)))


def test_fuel_trim_thresholds_and_direction():
    assert levels(assess(snap(idle={"ltft": 12.0})))["trim"] == "warn"
    assert levels(assess(snap(idle={"ltft": 17.0})))["trim"] == "bad"
    result = assess(snap(idle={"ltft": -12.0}))
    assert "cutting fuel" in next(f["detail"] for f in result["findings"] if f["id"] == "trim")
    assert levels(assess(snap(idle={"ltft": 9.9})))["trim"] == "ok"


def test_fuel_trim_is_not_judged_on_a_cold_engine():
    result = assess(snap(idle={"ltft": 18.0, "coolant_end": 40.0}))
    assert levels(result)["trim"] == "info"


def test_battery_and_charging():
    assert levels(assess(snap(idle={"volts_run": 12.9})))["charging"] == "warn"
    assert levels(assess(snap(idle={"volts_run": 12.2})))["charging"] == "bad"
    assert levels(assess(snap(idle={"volts_run": 15.6})))["charging"] == "warn"
    assert levels(assess(snap(idle={"volts_off": 11.8})))["battery_off"] == "warn"
    assert levels(assess(snap(idle={"volts_off": 11.2})))["battery_off"] == "bad"


def test_engine_off_skips_the_live_findings_and_says_so():
    result = assess(snap(idle={"running": False, "volts_run": 14.2, "volts_off": 12.5}))
    lv = levels(result)
    assert lv["engine"] == "info"
    assert not {"trim", "charging", "idle", "coolant"} & set(lv)  # nothing to say without a running engine
    assert lv["battery_off"] == "ok"


def test_idle_quality():
    assert levels(assess(snap(idle={"rpm_min": 650.0, "rpm_max": 900.0})))["idle"] == "warn"
    assert levels(assess(snap(idle={"rpm_mean": 1400.0, "rpm_min": 1390.0, "rpm_max": 1410.0})))["idle"] == "warn"
    assert "idle" not in levels(assess(snap(idle={"moving": True, "rpm_min": 600.0, "rpm_max": 3000.0})))


def test_overheating_only_counts_while_parked():
    assert levels(assess(snap(idle={"coolant_end": 109.0})))["coolant"] == "warn"
    assert "coolant" not in levels(assess(snap(idle={"coolant_end": 109.0, "moving": True})))


def test_findings_are_sorted_worst_first():
    result = assess(snap(codes={"mil": True, "stored": ["P0300"], "pending": []}, misfire_total=3.0))
    ranks = [{"bad": 3, "warn": 2, "info": 1, "ok": 0}[f["level"]] for f in result["findings"]]
    assert ranks == sorted(ranks, reverse=True)


def test_custom_limits_are_respected():
    from dataclasses import replace

    strict = replace(DEFAULT_THRESHOLDS, ltft_warn_pct=5.0)
    assert levels(assess(snap(idle={"ltft": 6.0}), strict))["trim"] == "warn"
    assert levels(assess(snap(idle={"ltft": 6.0})))["trim"] == "ok"


def test_the_demo_snapshot_triggers_the_headline_case():
    assert assess(DEMO_CHECK_SNAPSHOT)["verdict"] == "flags"


def test_empty_snapshot_does_not_crash():
    result = assess({})
    assert result["verdict"] in {"clear", "look"}  # nothing known, nothing flagged


def test_report_text_has_verdict_findings_and_caveat():
    result = assess(snap(codes={"mil": True, "stored": ["P0420"], "pending": []}))
    text = render_report(snap(), result, "20260101_101500")
    assert "Serious flags" in text and "P0420" in text and "5NPE24AF3GH283081" in text and CAVEAT in text
