from __future__ import annotations

import obd

from obd_dashboard import readers
from tests.fakes import C, FakeCar, Mon, MonTest, Q, R


class Null:
    def is_null(self):
        return True


def test_parse_numeric_value_and_unit():
    value, unit = readers.parse_value(C.COOLANT_TEMP, R(Q(90.123456, "celsius")))
    assert value == 90.123 and unit == "degree_Celsius"


def test_parse_null_and_garbage():
    assert readers.parse_value(C.RPM, Null()) == (None, None)
    assert readers.parse_value(C.RPM, R("not a quantity")) == (None, None)


def test_fuel_status_tokens():
    closed = R(("Closed loop, using oxygen sensor feedback to determine fuel mix", ""))
    cold = R(("Open loop due to insufficient engine temperature", ""))
    open_ = R(("Open loop due to driving conditions", ""))
    assert readers.parse_value(C.FUEL_STATUS, closed)[0] == "closed_loop"
    assert readers.parse_value(C.FUEL_STATUS, cold)[0] == "open_loop_cold"
    assert readers.parse_value(C.FUEL_STATUS, open_)[0] == "open_loop"


def test_query_swallows_exceptions():
    class Broken:
        def query(self, _cmd):
            raise OSError("port vanished")

    assert readers.query(Broken(), C.RPM).is_null()


def test_dtc_list():
    assert readers.dtc_list(R([("P0300", "Random misfire"), ("P0171", "")])) == ["P0300 Random misfire", "P0171"]
    assert readers.dtc_list(Null()) == []


def test_misfire_counts_pick_the_last_current_test():
    mon = {
        "MONITOR_MISFIRE_GENERAL": [
            ("Average misfire counts for last ten driving cycles", Q(9, "count"), True),
            ("Misfire counts for last/current driving cycles", Q(3, "count"), True),
        ],
        "MONITOR_MISFIRE_CYLINDER_2": [("Misfire counts for last/current driving cycles", Q(2, "count"), True)],
        "MONITOR_EVAP_150": [("Unknown", Q(1, "pascal"), True)],
    }
    assert readers.misfire_counts(mon) == {"total": 3.0, "cyl2": 2.0}


def test_read_monitors_and_formatting():
    class Conn:
        def query(self, _cmd):
            return R(Mon([MonTest("t", Q(1, "count"), passed=False)]))

    mon = readers.read_monitors(Conn(), [C.MONITOR_EVAP_150])
    assert mon["MONITOR_EVAP_150"][0][2] is False
    assert "[FAIL]" in "\n".join(readers.fmt_monitors(mon))
    assert readers.fmt_monitors({}) == ["  (none reported)"]


def test_read_monitors_skips_empty_replies():
    """A car that is shutting down answers Mode 06 with a frame that holds no tests."""

    class Conn:
        def query(self, _cmd):
            return R(Mon([]))

    assert readers.read_monitors(Conn(), [C.MONITOR_EVAP_150]) == {}


def test_read_codes_tells_no_codes_apart_from_no_answer():
    assert readers.read_codes(FakeCar())["stored"] == []  # answered: nothing stored yet

    class Silent:
        def query(self, _cmd):
            return obd.OBDResponse()

    assert readers.read_codes(Silent()) is None


def test_read_static_decodes_vin_and_counters_skip_text():
    car = FakeCar()
    static = readers.read_static(car, [C.VIN, C.FUEL_TYPE, C.WARMUPS_SINCE_DTC_CLEAR])
    assert static["VIN"] == "1M8GDM9AXKP042781"
    assert set(readers.read_counters(car, [C.VIN, C.FUEL_TYPE, C.WARMUPS_SINCE_DTC_CLEAR])) == {
        "WARMUPS_SINCE_DTC_CLEAR"
    }


def test_plan_sensors_splits_fast_rotating_static_and_monitors():
    plan = readers.plan_sensors(FakeCar())
    fast = {c.name for c in plan.fast}
    assert {"RPM", "SPEED", "COOLANT_TEMP"} <= fast
    rest = {c.name for c in plan.rest}
    assert "FUEL_STATUS" in rest and "VIN" not in rest and "STATUS" not in rest
    assert {c.name for c in plan.statics} >= {"VIN", "FUEL_TYPE"}
    assert all(c.name.startswith("MONITOR_") for c in plan.monitors)
    assert not (fast & rest)


def test_never_issues_clear_codes():
    # The whole app is read-only; make sure the clear command is not in any polled/static list.
    plan = readers.plan_sensors(FakeCar())
    names = {c.name for c in plan.polled + plan.statics + plan.monitors}
    assert "CLEAR_DTC" not in names and obd.commands.CLEAR_DTC.name not in names


def test_vin_keeps_a_trailing_one():
    """python-obd strips trailing '0'/'1'/'2' from Mode 09 strings; we must not lose the last VIN digit."""

    class Msg:
        data = bytearray(b"\x49\x02\x01" + b"1M8GDM9AXKP042781")

    class Resp(R):
        messages = [Msg()]

    class Conn:
        def query(self, _cmd):
            return Resp(bytearray(b"1M8GDM9AXKP04278"))  # what python-obd's decoder returns (one char short)

    assert readers.read_static(Conn(), [C.VIN])["VIN"] == "1M8GDM9AXKP042781"


def test_raw_text_falls_back_when_no_raw_frame():
    assert readers.raw_text(R("x")) is None
