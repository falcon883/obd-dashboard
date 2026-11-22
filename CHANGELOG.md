# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `obd-dashboard support`: writes an anonymous JSON report (adapter, protocol, supported sensors) to attach to bug reports.
- GPL-2.0-only license, contributing guide, security policy, issue and pull request templates, Dependabot.
- README: screenshots, tested-on table, safety and privacy notes.

## [1.0.0]

### Added
- Live dashboard (gauges, charts, health checks, event log) over Server-Sent Events.
- Automatic serial port and baud rate detection, with reconnect.
- Per-car garage: logs filed by VIN, car profile, nicknames, offline and NHTSA VIN decoding.
- Settings screen: editable alert limits (global and per car) and advanced options.
- Terminal mode (`log`), adapter test (`test`), port list (`ports`) and a simulated car (`--demo`).
- CI on Windows and Linux.
