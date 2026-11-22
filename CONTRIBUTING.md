# Contributing

Thanks for helping. The most useful thing you can do is **try it on your car** and send a
[compatibility report](https://github.com/falcon883/obd-dashboard/issues/new?template=compatibility_report.yml).
Run `obd-dashboard support` first and attach the file it writes.

Bug fixes, new health checks, translations of the UI and docs fixes are all welcome. For anything bigger than a small
fix, open an issue first so we can agree on the approach before you spend time on it.

## Ground rules

- **Read-only.** Nothing may write to the car or clear codes. `readers.SKIP` blocks `CLEAR_DTC` on purpose.
- **Privacy.** Do not add anything that sends data off the machine, and keep full VINs out of anything meant to be shared.
- **No hardware needed for tests.** Use the fake car in `tests/fakes.py`.

## Set up

    git clone https://github.com/falcon883/obd-dashboard.git
    cd obd-dashboard
    python -m venv .venv
    .venv\Scripts\activate          # Windows   (Linux/macOS: source .venv/bin/activate)
    pip install -e ".[dev]"
    obd-dashboard --demo            # simulated car, opens the dashboard

## Before you open a pull request

Backend:

    ruff check .
    ruff format --check .
    mypy
    pytest

Frontend (only if you touched `frontend/`):

    cd frontend
    npm ci
    npm run lint
    npm test
    npm run build

`npm run build` writes into `src/obd_dashboard/static/`. That folder is committed so people without Node can run the
app, so **commit the rebuilt files together with your source change**.

Optional browser check against the demo car (needs Playwright and Chrome): `python scripts/e2e_browser.py`.

CI runs all of this on Windows and Linux. A red Windows job is usually a newline problem, see below.

## Windows gotchas

- `Path.write_text()` writes `\r\n` on Windows. In tests that compare bytes or text, write with `write_bytes()`
  or pass `newline=""`.
- Always pass `encoding="utf-8"` when opening text files.
- Serial ports are `COM3`-style on Windows and `/dev/ttyUSB0` on Linux. Do not hard-code either.

## Adding a health check

Checks live in `rules.py` as pure functions of the readings and the limits. Put the number you compare against in the
field table in `userconfig.py` so it shows up in Settings and can be validated, then add a test with the fake car.
`frontend/src/format.js` keeps a copy of the defaults; a test fails if the two drift apart.

## Style

Small, plain functions with type hints, line length 120. Keep commit messages short and in the imperative
("Fix thermostat check on cold start").

By contributing you agree that your work is released under the project's license, GPL-2.0-only.
