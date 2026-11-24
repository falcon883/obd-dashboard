"""Used-car check: turn what the engine computer says into a short list of findings and one verdict.

`assess` is a pure function over a plain-dict snapshot (see `checkrun.collect`), so every rule can be tested
without a car. It only reports what the computer knows: it is a second pair of eyes before you buy, not a
substitute for a mechanic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from obd_dashboard.userconfig import DEFAULT_THRESHOLDS, Thresholds

OK, INFO, WARN, BAD = "ok", "info", "warn", "bad"
RANK = {OK: 0, INFO: 1, WARN: 2, BAD: 3}

VERDICTS = {
    "clear": "Nothing worrying found",
    "look": "Worth a closer look",
    "flags": "Serious flags",
}
CAVEAT = (
    "This reads the engine computer only. It does not see the transmission, brakes, airbags, body, rust or "
    "crash damage, and a car can look clean here and still have problems. Treat it as one more input, "
    "and still have a mechanic look the car over before you pay."
)

JUST_CLEARED_KM = 80  # fewer km than this since the codes were wiped: they were wiped very recently
CLEARED_RECENTLY_KM = 800  # ...and this is still "not long ago"
FEW_WARMUPS = 5
INCOMPLETE_LIMIT = 2  # this many unfinished self-tests make an inspection fail in most places
IDLE_SWING_RPM = 150  # warm idle that wanders by more than this is uneven
LTFT_BAD_FACTOR = 1.5
BATTERY_BAD_RUNNING_V = 12.5
BATTERY_BAD_OFF_V = 11.6
MISFIRE_NOTE = 1


def _finding(fid: str, level: str, title: str, detail: str = "") -> Dict[str, str]:
    return {"id": fid, "level": level, "title": title, "detail": detail}


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _km(km: float) -> str:
    return f"{km:.0f} km ({km * 0.621371:.0f} miles)"


def _codes(codes: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    if codes is None:
        return [_finding("codes", INFO, "Could not read trouble codes", "The car did not answer the code request.")]
    out: List[Dict[str, str]] = []
    stored, pending, mil = codes.get("stored") or [], codes.get("pending") or [], codes.get("mil")
    if mil:
        out.append(_finding("mil", BAD, "Check engine light is on", "The computer has switched the warning light on."))
    elif mil is False:
        out.append(_finding("mil", OK, "Check engine light is off"))
    if stored:
        out.append(
            _finding("stored", BAD, f"Stored trouble codes: {', '.join(stored)}", "Look these up before buying.")
        )
    if pending:
        out.append(
            _finding(
                "pending", WARN, f"Pending trouble codes: {', '.join(pending)}",
                "A fault was seen once but has not been confirmed yet.",
            )
        )  # fmt: skip
    if not stored and not pending:
        out.append(_finding("stored", OK, "No trouble codes stored or pending"))
    return out


def _readiness(snapshot: Dict[str, Any]) -> List[str]:
    return [t["name"] for t in snapshot.get("readiness") or [] if t.get("available") and not t.get("complete")]


def _pretty(name: str) -> str:
    return name.replace("_MONITORING", "").replace("_", " ").lower()


def _clearing(snapshot: Dict[str, Any]) -> List[Dict[str, str]]:
    since = snapshot.get("since_clear") or {}
    km, warmups = _num(since.get("distance_km")), _num(since.get("warmups"))
    incomplete = _readiness(snapshot)
    out: List[Dict[str, str]] = []

    recent = (km is not None and km < JUST_CLEARED_KM) or (km is None and warmups is not None and warmups < FEW_WARMUPS)
    if km is None and warmups is None:
        out.append(_finding("cleared", INFO, "Car does not report when codes were last cleared"))
    elif recent:
        when = f"{_km(km)} ago" if km is not None else f"{warmups:.0f} warm-ups ago"
        out.append(
            _finding(
                "cleared", WARN, "Trouble codes were cleared very recently",
                f"The fault memory was reset about {when}. That is also what happens after a battery "
                "disconnect or a new computer, so ask why.",
            )
        )  # fmt: skip
    elif km is not None and km < CLEARED_RECENTLY_KM:
        out.append(
            _finding(
                "cleared", INFO, "Codes were cleared not long ago",
                f"About {_km(km)} of driving since the fault memory was reset.",
            )
        )  # fmt: skip
    else:
        text = (
            f"{_km(km)} of driving since the last reset" if km is not None else "Fault memory has not been reset lately"
        )
        out.append(_finding("cleared", OK, "Fault memory has not been wiped recently", text))

    if not snapshot.get("readiness"):
        out.append(_finding("readiness", INFO, "Could not read the self-test (readiness) status"))
    elif len(incomplete) >= INCOMPLETE_LIMIT and recent:
        out.append(
            _finding(
                "readiness", BAD, f"Self-tests not finished after a recent reset ({len(incomplete)} pending)",
                "Not finished: " + ", ".join(_pretty(n) for n in incomplete) + ". A cleared fault can hide "
                "until these run again. This is the classic sign of codes wiped just before a sale.",
            )
        )  # fmt: skip
    elif len(incomplete) >= INCOMPLETE_LIMIT:
        out.append(
            _finding(
                "readiness", WARN, f"{len(incomplete)} self-tests have not finished",
                "Not finished: " + ", ".join(_pretty(n) for n in incomplete) + ". Many emissions inspections "
                "will not accept a car in this state.",
            )
        )  # fmt: skip
    elif incomplete:
        out.append(
            _finding("readiness", INFO, "One self-test has not finished", f"Not finished: {_pretty(incomplete[0])}.")
        )
    else:
        out.append(_finding("readiness", OK, "All self-tests have finished"))
    return out


def _mil_history(snapshot: Dict[str, Any]) -> List[Dict[str, str]]:
    km, mins = _num(snapshot.get("mil_km")), _num(snapshot.get("mil_minutes"))
    if (km is None or km <= 0) and (mins is None or mins <= 0):
        return []
    parts = []
    if km:
        parts.append(f"{_km(km)} driven")
    if mins:
        parts.append(f"{mins / 60:.1f} hours of engine time")
    return [
        _finding(
            "mil_history", WARN, "Check engine light has been on", "Since it came on: " + " and ".join(parts) + "."
        )
    ]


def _selftests(snapshot: Dict[str, Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    failed = snapshot.get("monitors_failed") or []
    if failed:
        out.append(
            _finding(
                "selftests", WARN, f"{len(failed)} on-board self-test result(s) out of range",
                "; ".join(failed[:4]) + (" ..." if len(failed) > 4 else "") + ". These raw results can be "
                "misleading on their own, so treat this as a question for a mechanic.",
            )
        )  # fmt: skip
    elif snapshot.get("monitors_read"):
        out.append(_finding("selftests", OK, "On-board self-test results look fine"))
    misfires = _num(snapshot.get("misfire_total"))
    if misfires is not None and misfires >= MISFIRE_NOTE:
        level = WARN if misfires >= DEFAULT_THRESHOLDS.misfire_rise else INFO
        out.append(_finding("misfire", level, f"Misfires counted in the last drive: {misfires:.0f}"))
    return out


def _idle(snapshot: Dict[str, Any], limits: Thresholds) -> List[Dict[str, str]]:
    idle = snapshot.get("idle") or {}
    out: List[Dict[str, str]] = []
    volts_off, volts_run = _num(idle.get("volts_off")), _num(idle.get("volts_run"))
    if not idle.get("running"):
        out.append(
            _finding(
                "engine", INFO, "Engine was not running",
                "Start the engine and run the check again for fuel trim, charging and idle results.",
            )
        )  # fmt: skip
        volts_run = None
    if volts_off is not None and volts_off < limits.battery_low_off_v:
        level = BAD if volts_off < BATTERY_BAD_OFF_V else WARN
        out.append(_finding("battery_off", level, f"Battery is low with the engine off ({volts_off:.1f} V)"))
    elif volts_off is not None:
        out.append(_finding("battery_off", OK, f"Battery with the engine off: {volts_off:.1f} V"))
    if volts_run is not None:
        if volts_run < limits.battery_low_running_v:
            level = BAD if volts_run < BATTERY_BAD_RUNNING_V else WARN
            out.append(
                _finding(
                    "charging", level, f"Charging voltage is low ({volts_run:.1f} V)",
                    "The alternator or battery may be tired. A healthy running car reads about 13.5 to 14.7 V.",
                )
            )  # fmt: skip
        elif volts_run > limits.battery_high_running_v:
            out.append(_finding("charging", WARN, f"Charging voltage is high ({volts_run:.1f} V)"))
        else:
            out.append(_finding("charging", OK, f"Charging voltage is normal ({volts_run:.1f} V)"))
    if not idle.get("running"):
        return out

    warm = _num(idle.get("coolant_end")) is not None and idle["coolant_end"] >= limits.warmed_up_c
    ltft = _num(idle.get("ltft"))
    if ltft is not None:
        if not warm:
            out.append(
                _finding(
                    "trim", INFO, f"Long-term fuel trim {ltft:+.1f}% (engine not warm yet)",
                    "Trims mean more once the engine is warm. Check again after a longer run.",
                )
            )  # fmt: skip
        elif abs(ltft) >= limits.ltft_warn_pct * LTFT_BAD_FACTOR:
            out.append(_finding("trim", BAD, f"Fuel trim is far off ({ltft:+.1f}%)", _trim_hint(ltft)))
        elif abs(ltft) >= limits.ltft_warn_pct:
            out.append(_finding("trim", WARN, f"Fuel trim is off ({ltft:+.1f}%)", _trim_hint(ltft)))
        else:
            out.append(_finding("trim", OK, f"Fuel trim is fine ({ltft:+.1f}%)"))

    cool = _num(idle.get("coolant_end"))
    if cool is not None and cool > limits.coolant_warn_c and not idle.get("moving"):
        out.append(
            _finding(
                "coolant", WARN, f"Running hot while parked ({cool:.0f} °C)",
                "Cooling fans, thermostat or coolant level are worth checking.",
            )
        )  # fmt: skip

    swing = None
    if _num(idle.get("rpm_min")) is not None and _num(idle.get("rpm_max")) is not None:
        swing = idle["rpm_max"] - idle["rpm_min"]
    if not idle.get("moving") and swing is not None and warm:
        mean = _num(idle.get("rpm_mean")) or 0
        if swing > IDLE_SWING_RPM:
            out.append(
                _finding(
                    "idle", WARN, f"Idle is uneven (wandered {swing:.0f} rpm)",
                    "Can point to a vacuum leak, dirty throttle body or a misfire.",
                )
            )  # fmt: skip
        elif not limits.idle_rpm_min <= mean <= limits.idle_rpm_max:
            out.append(_finding("idle", WARN, f"Idle speed is unusual ({mean:.0f} rpm)"))
        else:
            out.append(_finding("idle", OK, f"Idle is steady ({mean:.0f} rpm)"))
    return out


def _trim_hint(ltft: float) -> str:
    if ltft > 0:
        return "The computer is adding fuel to compensate. Often a vacuum leak, a dirty air sensor or a weak fuel pump."
    return "The computer is cutting fuel. Often leaking injectors, a bad sensor or too much fuel pressure."


def assess(snapshot: Dict[str, Any], limits: Thresholds = DEFAULT_THRESHOLDS) -> Dict[str, Any]:
    """-> {"verdict", "headline", "findings": [{id, level, title, detail}], "caveat"} (worst first)."""
    findings = (
        _codes(snapshot.get("codes"))
        + _clearing(snapshot)
        + _mil_history(snapshot)
        + _selftests(snapshot)
        + _idle(snapshot, limits)
    )
    findings.sort(key=lambda f: -RANK[f["level"]])  # stable: keeps the order above within a level
    worst = max((RANK[f["level"]] for f in findings), default=0)
    verdict = "flags" if worst >= RANK[BAD] else "look" if worst >= RANK[WARN] else "clear"
    return {"verdict": verdict, "headline": VERDICTS[verdict], "findings": findings, "caveat": CAVEAT}


def render_report(snapshot: Dict[str, Any], result: Dict[str, Any], stamp: str) -> str:
    """The plain-text version that gets saved next to the logs."""
    marks = {OK: "[ok]  ", INFO: "[info]", WARN: "[warn]", BAD: "[BAD] "}
    lines = [
        f"USED-CAR CHECK {stamp}",
        f"Car: {snapshot.get('car') or 'unknown'}   VIN: {snapshot.get('vin') or 'not readable'}",
        f"Verdict: {result['headline']}",
        "",
    ]
    for f in result["findings"]:
        lines.append(f"{marks[f['level']]} {f['title']}")
        if f["detail"]:
            lines.append(f"       {f['detail']}")
    idle = snapshot.get("idle") or {}
    if idle.get("samples"):
        lines += ["", f"Live sample: {idle['samples']} readings"]
    lines += ["", result["caveat"], ""]
    return "\n".join(lines)
