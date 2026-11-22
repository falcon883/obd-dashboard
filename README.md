# OBD Dashboard

Live dashboard and logger for an ELM327 OBD-II adapter. FastAPI backend + React frontend.
**Read-only**: it never clears codes or writes anything to the car.

## Install (Windows, in your venv)

    git clone https://github.com/<you>/obd-dashboard.git
    cd obd-dashboard
    pip install -e .
    obd-dashboard

`-e` (editable) means the installed command runs straight from this folder, so updating is just `git pull`.
The built web UI is committed to the repo, so you do not need Node.

Open http://localhost:8000 and press **Start monitoring**.
Adapter plugged in, MS/HS switch on **HS**, engine running (ignition ON is enough for codes and basic info).
The serial port and baud rate are detected automatically.

## Updating

    cd obd-dashboard
    git pull

That is all (restart `obd-dashboard` if it is running). If a release adds a new dependency, also run `pip install -e .`.

## Commands

| Command | What it does |
|---|---|
| `obd-dashboard` | web dashboard (same as `obd-dashboard serve`) |
| `obd-dashboard --demo` | simulated car, no hardware needed |
| `obd-dashboard --autostart` | start logging as soon as the server starts |
| `obd-dashboard --host 0.0.0.0` | also open it from your phone (same Wi-Fi) |
| `obd-dashboard --com COM4 --baud 38400` | force the port / baud instead of auto-detect |
| `obd-dashboard log` | terminal only: live status line + files, Ctrl+C to finish |
| `obd-dashboard test` | raw adapter test (prints the ELM327's replies) |
| `obd-dashboard ports` | list serial ports |

Other flags: `--no-beep`, `--no-vin-lookup`, `--output-dir logs`, `--no-browser`, `-v` (debug log).

Logs are filed per car: `logs/<VIN>/<time>_data.csv`, `_report.txt`, `_summary.json`, plus a `car.json` profile.
`obd-dashboard garage` lists your cars; `obd-dashboard garage rename <VIN> "Daily Sonata"` sets a nickname.

## Settings

The **Settings** button (top right) opens two tabs:

- **Alert limits**: every threshold the health rules use (coolant, battery, fuel trim, catalyst, idle, misfires...).
  Temperatures show in your chosen unit. Pick *All cars* to change the defaults, or pick one car to give it its own
  limits (a diesel and a petrol car do not share the same normal). The blue bar marks what you changed; `↺` puts a
  value back.
- **Advanced**: beeps, the online make/model lookup, polling speed, trouble-code check interval, reconnect behaviour.

Changes apply from the next session. They are saved in `logs/settings.json` (only what you changed, so new
defaults in a future update still reach you), and each report starts with the limits it ran under.

## Project layout

    src/obd_dashboard/
      settings.py    Settings + Tuning (no global state)
      connection.py  port discovery, baud probing, opening the link
      readers.py     read-only OBD queries, sensor planning
      rules.py       health rules (pure functions)
      userconfig.py  editable limits + advanced options (validation, settings.json)
      garage.py      per-car folders, profiles, safe downloads
      vin.py         VIN -> year/make offline, model/engine via NHTSA
      report.py      CSV columns, report file, end-of-run summary
      session.py     the logging session (connect -> baseline -> loop -> summary)
      hub.py         live state + fan-out to browsers (thread-safe)
      api.py         FastAPI routes, SSE stream, serves the UI
      demo.py        simulated car
      cli.py, console.py, diagnose.py, notify.py, types.py
    frontend/        React + Vite (builds into src/obd_dashboard/static)
    tests/           pytest (fake car, no hardware needed)
    scripts/         browser end-to-end check (Playwright)

How the pieces connect: `Session` reads the car and reports to a `Sink`; `Hub` is the sink that keeps the
latest state and streams it to every open browser tab over Server-Sent Events; `rules.py` decides what is an alert.

## Development

    pip install -e ".[dev]"
    pytest                 # backend tests
    ruff check . && ruff format --check .
    mypy                   # strict

    cd frontend
    npm install
    npm run dev            # hot reload on :5173, proxies /api to :8000 (run obd-dashboard --demo too)
    npm run lint && npm test
    npm run build          # writes ../src/obd_dashboard/static

The built UI in `src/obd_dashboard/static/` is committed on purpose so users without Node can run the app.
After changing anything in `frontend/`, run `npm run build` and commit the new `static/` files with it.
GitHub Actions (`.github/workflows/ci.yml`) runs lint, type-check and tests on Windows and Linux for every push.

## Security notes

- Listens on 127.0.0.1 by default. `--host 0.0.0.0` lets anyone on your network view *and start/stop* the logger.
- No CORS headers are sent, so other websites cannot call the API from your browser.
