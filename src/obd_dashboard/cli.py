"""Command line: `obd-dashboard` (web UI), `obd-dashboard log` (terminal only), `test`, `ports`."""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from pathlib import Path
from typing import List, Optional

from obd_dashboard import __version__
from obd_dashboard.settings import Settings

COMMANDS = {"serve", "log", "test", "ports"}


def _session_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--com", default=None, help="serial port, e.g. COM4 (default: auto-detect CH340)")
    p.add_argument("--baud", type=int, default=0, help="default 0 = auto-detect")
    p.add_argument("--no-beep", action="store_true", help="silence alert beeps")
    p.add_argument("--output-dir", type=Path, default=Path("logs"), help="where CSV/report files go")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    ap = argparse.ArgumentParser(prog="obd-dashboard", description="Live OBD-II dashboard and logger (read-only).")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="command")

    serve = sub.add_parser("serve", parents=[common], help="start the web dashboard (default)")
    serve.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to open it from your phone")
    serve.add_argument("--port", type=int, default=8000, help="web server port")
    serve.add_argument("--demo", action="store_true", help="simulated car, no hardware needed")
    serve.add_argument("--autostart", action="store_true", help="start logging immediately")
    serve.add_argument("--no-browser", action="store_true")
    _session_args(serve)
    serve.add_argument("--no-vin-lookup", action="store_true", help="never contact NHTSA to name the car")

    log = sub.add_parser("log", parents=[common], help="log to the terminal and files, no web UI")
    _session_args(log)
    log.add_argument("--no-vin-lookup", action="store_true", help="never contact NHTSA to name the car")

    test = sub.add_parser("test", parents=[common], help="raw adapter connection test")
    test.add_argument("--com", default=None)
    test.add_argument("--baud", type=int, default=0)

    garage = sub.add_parser("garage", parents=[common], help="list your cars and their logs, or rename a car")
    garage.add_argument("action", nargs="?", choices=["list", "rename"], default="list")
    garage.add_argument("vin", nargs="?", help="VIN of the car (for rename)")
    garage.add_argument("name", nargs="*", help="new nickname (for rename)")
    garage.add_argument("--output-dir", type=Path, default=Path("logs"))

    sub.add_parser("ports", parents=[common], help="list serial ports")
    return ap


def _serve(a: argparse.Namespace) -> int:
    import uvicorn

    from obd_dashboard.api import create_app

    settings = Settings(
        host=a.host, http_port=a.port, open_browser=not a.no_browser, com=a.com, baud=a.baud,
        demo=a.demo, autostart=a.autostart, beep=not a.no_beep, output_dir=a.output_dir,
        lookup_vin=not a.no_vin_lookup,
    )  # fmt: skip
    print(f"Dashboard: http://localhost:{a.port}   (Ctrl+C to quit)")
    if a.host not in ("127.0.0.1", "localhost"):
        print("Reachable from other devices on your network - anyone there can view and control it.")
    uvicorn.run(create_app(settings), host=a.host, port=a.port, log_level="warning")
    return 0


def _log(a: argparse.Namespace) -> int:
    from obd_dashboard.console import ConsoleSink
    from obd_dashboard.session import Session

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())  # Ctrl+C = finish cleanly and write the summary
    settings = Settings(
        com=a.com, baud=a.baud, beep=not a.no_beep, output_dir=a.output_dir, lookup_vin=not a.no_vin_lookup
    )
    print("Logging... press Ctrl+C to stop.")
    Session(settings, ConsoleSink(), stop).run()
    return 0


def _test(a: argparse.Namespace) -> int:
    from obd_dashboard.diagnose import run

    return run(a.com, a.baud)


def _garage(a: argparse.Namespace) -> int:
    from obd_dashboard.garage import Garage

    garage = Garage(a.output_dir)
    if a.action == "rename":
        if not a.vin or not a.name:
            print('Usage: obd-dashboard garage rename <VIN> "new name"')
            return 2
        car = garage.rename(a.vin.upper(), " ".join(a.name))
        print(f"Renamed to '{car.display_name}'." if car else f"No car with VIN {a.vin} in {a.output_dir}.")
        return 0 if car else 1
    cars = garage.cars()
    for car in cars:
        sessions = garage.sessions(car.vin)
        name = f"{car.title} ({car.nickname})" if car.nickname else car.title
        print(f"{name}   VIN {car.vin}   {len(sessions)} session(s), last seen {car.last_seen[:10]}")
        for s in sessions[:10]:
            mins = f"{s['duration_s'] / 60:.1f} min" if "duration_s" in s else "incomplete"
            path = garage.car_dir(car.vin) / s["files"]["csv"]
            print(f"    {s['stamp']}  {mins:>11}  {s.get('verdict', '?'):<5}  {path}")
    if not cars:
        print(f"No cars yet in {a.output_dir.resolve()} - run a session first.")
    if garage.unsorted():
        print(f"\n{len(garage.unsorted())} older log file(s) sit loose in {a.output_dir}; they predate the garage.")
    return 0


def _ports(_a: argparse.Namespace) -> int:
    from serial.tools import list_ports

    found = list(list_ports.comports())
    for p in found:
        print(f"{p.device}\t{p.description}")
    if not found:
        print("No serial ports found.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or (args[0].startswith("-") and args[0] not in ("-h", "--help", "--version")):
        args.insert(0, "serve")  # plain `obd-dashboard --demo` means `obd-dashboard serve --demo`
    parsed = build_parser().parse_args(args)
    logging.basicConfig(
        level=logging.DEBUG if getattr(parsed, "verbose", False) else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
    )  # fmt: skip
    logging.getLogger("pint").setLevel(logging.ERROR)  # python-obd's unit library is noisy on import
    handlers = {"serve": _serve, "log": _log, "test": _test, "ports": _ports, "garage": _garage}
    return handlers[parsed.command or "serve"](parsed)
