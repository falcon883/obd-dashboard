# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed
- Crash on start with a real car ("'<' not supported between NoneType and int"): python-OBD lists its two adapter commands
  among the car's supported commands, and they have no mode.
- False battery alerts: "Charging low" in the first second after the engine starts, "Weak battery" while cranking, and
  "Weak battery 0.0 V" at key-off. Battery alerts now need the problem to last 5 seconds, and readings below 6 V
  (the engine computer winding down, or the adapter losing power) count as no reading.
- The report no longer says "Codes at end: none" and "Mode 06 failures: none" when the car had simply stopped
  answering at the end. It keeps the last known codes and test failures and says so.

### Added
- `obd-dashboard support`: writes an anonymous JSON report (adapter, protocol, supported sensors, trouble codes, a raw
  freeze-frame probe) to attach to bug reports.
- History screen: one point per drive for warm-up time, hottest coolant, charging voltage, long-term fuel trim and warm
  idle speed, with the normal range shaded, plus a table of every drive with report and CSV links. Computed from the
  existing CSV logs, so old drives show up too (`GET /api/history/{vin}`).
- GPL-2.0-only license, contributing guide, security policy, issue and pull request templates, Dependabot.
- README: screenshots, tested-on table (two cars), safety and privacy notes.

## [1.0.0]

### Added
- Live dashboard (gauges, charts, health checks, event log) over Server-Sent Events.
- Automatic serial port and baud rate detection, with reconnect.
- Per-car garage: logs filed by VIN, car profile, nicknames, offline and NHTSA VIN decoding.
- Settings screen: editable alert limits (global and per car) and advanced options.
- Terminal mode (`log`), adapter test (`test`), port list (`ports`) and a simulated car (`--demo`).
- CI on Windows and Linux.
