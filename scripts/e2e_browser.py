"""Browser end-to-end check with a simulated car (needs: pip install playwright, a Chrome/Chromium).

    python scripts/e2e_browser.py [--chrome /usr/bin/google-chrome]

Starts the real FastAPI app on a spare port, clicks Start/Stop in a real browser, and writes
screenshots to ./e2e_out/. Exits non-zero if the page logs console errors.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.fakes import FakeCar  # noqa: E402

from obd_dashboard.api import create_app  # noqa: E402
from obd_dashboard.hub import Hub  # noqa: E402
from obd_dashboard.session import Session  # noqa: E402
from obd_dashboard.settings import Settings, Tuning  # noqa: E402
from obd_dashboard.vin import CarInfo  # noqa: E402

PORT = 8124


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome", default=None, help="path to a Chrome/Chromium binary")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    out = Path("e2e_out")
    out.mkdir(exist_ok=True)
    settings = Settings(
        http_port=PORT, open_browser=False, beep=False, lookup_vin=True, output_dir=Path(tempfile.mkdtemp()),
        tuning=Tuning(target_loop=0.4, slow_every=3.0),
    )  # fmt: skip

    def factory(cfg: Settings, sink: Hub, stop: threading.Event) -> Session:
        return Session(
            replace(cfg, com="FAKE0"),
            sink,
            stop,
            connector=lambda _p, _b: FakeCar(),
            vin_lookup=lambda v: CarInfo(v, 2016, "Hyundai", "Sonata", None, "2.4 L 4-cyl", "nhtsa"),
        )

    app = create_app(settings, Hub(settings, session_factory=factory))
    threading.Thread(
        target=uvicorn.run, args=(app,), kwargs={"port": PORT, "log_level": "warning"}, daemon=True
    ).start()
    time.sleep(2)

    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chrome, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.goto(f"http://localhost:{PORT}")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(out / "0_start.png"))
        page.get_by_text("Start monitoring").click()
        page.wait_for_timeout(14000)
        page.screenshot(path=str(out / "1_live.png"), full_page=True)
        page.get_by_role("button", name="Stop").click()
        page.wait_for_timeout(4000)
        page.screenshot(path=str(out / "2_finished.png"), full_page=True)
        mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        mobile.goto(f"http://localhost:{PORT}")
        mobile.wait_for_timeout(1500)
        mobile.screenshot(path=str(out / "3_mobile.png"), full_page=True)
        browser.close()
    print("console errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
