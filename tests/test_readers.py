from __future__ import annotations

from typing import Any

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
    assert {"RPM", "SPEED", "ENGINE_LOAD", "THROTTLE_POS", "SHORT_FUEL_TRIM_1"} <= fast
    steady = {c.name for c in plan.steady}
    assert {"COOLANT_TEMP", "LONG_FUEL_TRIM_1", "CONTROL_MODULE_VOLTAGE"} <= steady
    rest = {c.name for c in plan.rest}
    assert "FUEL_STATUS" in rest and "VIN" not in rest and "STATUS" not in rest
    assert {c.name for c in plan.statics} >= {"VIN", "FUEL_TYPE"}
    assert all(c.name.startswith("MONITOR_") for c in plan.monitors)
    assert not (fast & rest) and not (steady & rest) and not (fast & steady)
    assert {c.name for c in plan.polled} == fast | steady | rest


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


# --- freeze frame (Mode 2) ---------------------------------------------------------------------------------------


def _reply(*data: int) -> Any:
    from obd import ECU
    from obd.protocols.protocol import Frame, Message

    message = Message([Frame("7E8")])
    message.data = bytearray(data)
    message.ecu = ECU.ENGINE
    return message


def test_frame_request_carries_the_frame_number() -> None:
    cmd = readers.frame_command(obd.commands.DTC_COOLANT_TEMP)
    assert cmd.command == b"020500" and cmd.bytes == obd.commands.DTC_COOLANT_TEMP.bytes + 1
    assert readers.frame_command(obd.commands.DTC_RPM).command == b"020C00"


def test_frame_replies_decode_to_the_right_numbers() -> None:
    """python-OBD alone turns these replies into -40 C, 0 % and 6.5 rpm; the frame byte shifts everything."""
    coolant = readers.frame_command(obd.commands.DTC_COOLANT_TEMP)([_reply(0x42, 0x05, 0x00, 0x82)])
    assert coolant.value.magnitude == 90
    load = readers.frame_command(obd.commands.DTC_ENGINE_LOAD)([_reply(0x42, 0x04, 0x00, 0x80)])
    assert round(load.value.magnitude) == 50
    rpm = readers.frame_command(obd.commands.DTC_RPM)([_reply(0x42, 0x0C, 0x00, 0x1A, 0xF8)])
    assert rpm.value.magnitude == 1726
    code = readers.frame_command(obd.commands.DTC_FREEZE_DTC)([_reply(0x42, 0x02, 0x00, 0x04, 0x56)])
    assert code.value[0] == "P0456"


def test_freeze_frame_lists_what_the_car_answers() -> None:
    car = FakeCar()
    car.supported_commands = set(car.supported_commands) | {
        obd.commands.DTC_FREEZE_DTC,
        obd.commands.DTC_COOLANT_TEMP,
        obd.commands.DTC_RPM,
    }
    car.freeze = {"DTC_COOLANT_TEMP": Q(93, "celsius"), "DTC_RPM": Q(1500, "rpm")}
    lines = readers.freeze_frame(car)
    assert len(lines) == 2 and "DTC_COOLANT_TEMP" in lines[0] and "93" in lines[0] and "DTC_RPM" in lines[1]


def test_freeze_frame_stops_asking_when_nothing_is_stored() -> None:
    asked: list[str] = []

    class Quiet(FakeCar):
        def query(self, cmd: Any, force: bool = False) -> Any:
            if cmd.mode == 2:
                asked.append(cmd.name)
            return super().query(cmd, force)

    car = Quiet()
    car.supported_commands = set(car.supported_commands) | {
        getattr(obd.commands, n)
        for n in ("DTC_FREEZE_DTC", "DTC_ENGINE_LOAD", "DTC_COOLANT_TEMP", "DTC_RPM", "DTC_SPEED")
    }
    assert readers.freeze_frame(car) == ["    (car returned no freeze-frame data)"]
    assert len(asked) == readers.FREEZE_GIVE_UP_AFTER
