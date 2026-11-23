"""A fake python-obd connection that behaves like a (slightly unhealthy) car."""

from __future__ import annotations

from typing import Any

import obd

C = obd.commands
Q = obd.Unit.Quantity

SUPPORTED_NAMES = [
    "RPM", "SPEED", "ENGINE_LOAD", "COOLANT_TEMP", "THROTTLE_POS", "SHORT_FUEL_TRIM_1", "LONG_FUEL_TRIM_1",
    "INTAKE_PRESSURE", "TIMING_ADVANCE", "CONTROL_MODULE_VOLTAGE", "FUEL_STATUS", "INTAKE_TEMP", "FUEL_LEVEL",
    "CATALYST_TEMP_B1S1", "O2_B1S2", "FUEL_RAIL_PRESSURE_ABS", "RUN_TIME", "ABSOLUTE_LOAD", "VIN", "CVN",
    "FUEL_TYPE", "WARMUPS_SINCE_DTC_CLEAR", "STATUS", "GET_DTC", "GET_CURRENT_DTC", "MONITOR_MISFIRE_GENERAL",
    "MONITOR_MISFIRE_CYLINDER_1", "MONITOR_EVAP_150",
]  # fmt: skip
# python-OBD also lists its two adapter commands (no mode, no pid) among a real car's supported commands.
SUPPORTED = {getattr(C, n) for n in SUPPORTED_NAMES} | {C.ELM_VERSION, C.ELM_VOLTAGE}


class R:
    def __init__(self, value: Any) -> None:
        self.value = value

    def is_null(self) -> bool:
        return False


class MonTest:
    def __init__(self, desc: str, value: Any, passed: bool = True) -> None:
        self.desc, self.value, self.passed = desc, value, passed


class Mon:
    def __init__(self, tests: list[MonTest]) -> None:
        self.tests = tests


class Status:
    MIL = False


class FakeCar:
    """Each RPM query advances the 'clock'. Coolant climbs past the 102C warning; a P0300 appears later."""

    def __init__(self, *, dead_after: int | None = None) -> None:
        self.n = 0
        self.dead_after = dead_after  # stop answering after this many RPM queries
        self.closed = False
        self.supported_commands = SUPPORTED

    def supports(self, cmd: Any) -> bool:
        return cmd in SUPPORTED

    def protocol_name(self) -> str:
        return "ISO 15765-4 (CAN 11/500) [FAKE]"

    def port_name(self) -> str:
        return "FAKE0"

    def status(self) -> str:
        return "Car Connected"

    def is_connected(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True

    def query(self, cmd: Any) -> Any:  # noqa: C901 - a lookup table, deliberately flat
        name = cmd.name
        if self.dead_after is not None and self.n >= self.dead_after:
            return obd.OBDResponse()
        if name == "RPM":
            self.n += 1
            return R(Q(740 + self.n % 7, "rpm"))
        table = {
            "SPEED": lambda: Q(0 if self.n < 10 else 40, "kph"),
            "COOLANT_TEMP": lambda: Q(70 + min(self.n, 40) * 1.2, "celsius"),  # tops out at 118C
            "ENGINE_LOAD": lambda: Q(18.0, "percent"),
            "THROTTLE_POS": lambda: Q(18.0, "percent"),
            "FUEL_LEVEL": lambda: Q(18.0, "percent"),
            "ABSOLUTE_LOAD": lambda: Q(18.0, "percent"),
            "SHORT_FUEL_TRIM_1": lambda: Q(1.5, "percent"),
            "LONG_FUEL_TRIM_1": lambda: Q(3.1, "percent"),
            "INTAKE_PRESSURE": lambda: Q(35, "kilopascal"),
            "FUEL_RAIL_PRESSURE_ABS": lambda: Q(4890, "kilopascal"),
            "TIMING_ADVANCE": lambda: Q(5.0, "degree"),
            "CONTROL_MODULE_VOLTAGE": lambda: Q(14.27, "volt"),
            "O2_B1S2": lambda: Q(0.58, "volt"),
            "ELM_VOLTAGE": lambda: Q(14.2, "volt"),
            "INTAKE_TEMP": lambda: Q(28, "celsius"),
            "CATALYST_TEMP_B1S1": lambda: Q(532.6, "celsius"),
            "RUN_TIME": lambda: Q(self.n, "second"),
            "WARMUPS_SINCE_DTC_CLEAR": lambda: Q(42, "count"),
        }
        if name in table:
            return R(table[name]())
        other = {
            "ELM_VERSION": lambda: R("ELM327 v1.5"),
            "FUEL_STATUS": lambda: R(("Closed loop, using oxygen sensor feedback to determine fuel mix", "")),
            "VIN": lambda: R(bytearray(b"1M8GDM9AXKP042781")),
            "CVN": lambda: R("0f16f81c"),
            "FUEL_TYPE": lambda: R("Gasoline"),
            "STATUS": lambda: R(Status()),
            "GET_DTC": lambda: R([("P0300", "Random misfire")] if self.n > 20 else []),
            "GET_CURRENT_DTC": lambda: R([]),
            "MONITOR_MISFIRE_GENERAL": lambda: R(
                Mon([MonTest("Misfire counts for last/current driving cycles", Q(3 + (self.n > 15) * 12, "count"))])
            ),
            "MONITOR_MISFIRE_CYLINDER_1": lambda: R(
                Mon([MonTest("Misfire counts for last/current driving cycles", Q(0, "count"))])
            ),
            "MONITOR_EVAP_150": lambda: R(Mon([MonTest("Unknown", Q(-1502, "pascal"), passed=False)])),
        }
        if name in other:
            return other[name]()
        return obd.OBDResponse()
