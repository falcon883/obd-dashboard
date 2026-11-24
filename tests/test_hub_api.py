from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from obd_dashboard.api import create_app, event_stream
from obd_dashboard.hub import Hub, SessionBusy
from obd_dashboard.settings import Settings


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def hub(settings):
    h = Hub(settings)
    yield h
    h.end()
    h.join(3)


@pytest.fixture
def client(settings, hub, tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<h1>ui</h1>")
    app = create_app(Settings(**{**settings.__dict__, "static_dir": ui}), hub)
    with TestClient(app) as c:
        yield c


def test_state_starts_idle(client):
    body = client.get("/api/state").json()
    assert body["status"]["state"] == "idle" and body["running"] is False and body["history"] == []


def test_serves_the_built_ui(client):
    assert "<h1>ui</h1>" in client.get("/").text


def test_friendly_page_when_ui_is_not_built(settings, tmp_path):
    app = create_app(Settings(**{**settings.__dict__, "static_dir": tmp_path / "nope"}))
    with TestClient(app) as c:
        assert "not built" in c.get("/").text


def test_demo_session_start_stream_state_and_stop(client, hub):
    assert client.post("/api/start", json={"demo": True}).json() == {"ok": True, "message": "started"}
    assert wait_for(lambda: client.get("/api/state").json()["last"] is not None)
    state = client.get("/api/state").json()
    assert state["running"] and state["demo"] and state["info"]["demo"] is True
    assert state["history"][0]["v"]["RPM"] > 0

    assert client.post("/api/start", json={"demo": True}).status_code == 409  # one session at a time
    assert client.post("/api/stop").json()["ok"] is True
    assert wait_for(lambda: client.get("/api/state").json()["status"]["state"] == "finished")
    assert client.get("/api/state").json()["status"]["result"]["summary"] == ["Demo session ended."]


@pytest.mark.parametrize("body", [{"port": "COM4; rm -rf /"}, {"baud": -1}, {"baud": "fast"}, {"port": "x" * 100}])
def test_start_rejects_bad_input(client, body):
    assert client.post("/api/start", json=body).status_code == 422


def test_ports_endpoint(client, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "obd_dashboard.api.list_ports.comports", lambda: [SimpleNamespace(device="COM4", description="CH340")]
    )
    assert client.get("/api/ports").json() == [{"device": "COM4", "description": "CH340"}]


def test_no_cors_headers_so_other_sites_cannot_drive_the_api(client):
    r = client.options(
        "/api/start", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in r.headers


def test_hub_rejects_a_second_session(hub):
    hub.start(demo=True)
    with pytest.raises(SessionBusy):
        hub.start(demo=True)


def test_hub_survives_a_crashing_session(settings):
    class Boom:
        def __init__(self, *_a):
            pass

        def run(self):
            raise ValueError("kaput")

    h = Hub(settings, session_factory=Boom)
    h.start()
    assert wait_for(lambda: h.snapshot()["status"]["state"] == "error")
    assert "ValueError: kaput" in h.snapshot()["status"]["message"]
    h.join(2)


def test_hub_passes_port_and_baud_to_the_session(settings):
    seen = {}

    class Spy:
        def __init__(self, cfg, _sink, _stop):
            seen["com"], seen["baud"] = cfg.com, cfg.baud

        def run(self):
            pass

    h = Hub(settings, session_factory=Spy)
    h.start(port="COM7", baud=9600)
    h.join(2)
    assert seen == {"com": "COM7", "baud": 9600}


def test_sse_stream_sends_snapshot_then_live_events_then_cleans_up(hub):
    async def scenario():
        hub.attach_loop(asyncio.get_running_loop())
        disconnected = False

        async def is_disconnected():
            return disconnected

        stream = event_stream(hub, is_disconnected, ping_every=0.05)
        first = await stream.__anext__()
        assert first.startswith("event: snapshot") and json.loads(first.split("data: ")[1])["running"] is False

        hub.on_row({"t": 1.0, "ts": "x", "values": {"RPM": 800}})  # type: ignore[typeddict-item]
        row = await stream.__anext__()
        assert row.startswith("event: row") and '"RPM": 800' in row
        assert await stream.__anext__() == ": ping\n\n"  # idle -> keep-alive

        disconnected = True
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()
        assert not hub._clients

    asyncio.run(scenario())


def test_slow_client_is_dropped_and_told_to_resync(hub):
    async def scenario():
        hub.attach_loop(asyncio.get_running_loop())

        async def never():
            return False

        stream = event_stream(hub, never, ping_every=0.05)
        await stream.__anext__()  # snapshot
        (queue,) = hub._clients
        for i in range(queue.maxsize):
            queue.put_nowait(f"m{i}")
        hub._deliver("overflow")  # queue full -> client discarded
        assert not hub.is_subscribed(queue)
        for _ in range(queue.maxsize):
            await stream.__anext__()  # drain what was queued
        with pytest.raises(StopAsyncIteration):  # then the stream ends so EventSource reconnects
            await stream.__anext__()

    asyncio.run(scenario())


def test_snapshot_is_safe_while_the_logger_thread_writes(hub):
    import threading

    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            hub.on_row({"t": float(i), "ts": "x", "values": {"RPM": i}})  # type: ignore[typeddict-item]
            i += 1

    t = threading.Thread(target=writer)
    t.start()
    try:
        for _ in range(300):
            hub.snapshot()  # would raise "deque mutated during iteration" without the lock
    finally:
        stop.set()
        t.join()


def test_garage_endpoints(client, settings):
    from obd_dashboard.garage import Garage

    g = Garage(settings.output_dir)
    vin = "5NPE24AF3GH283081"
    g.register(vin)
    folder = g.car_dir(vin)
    (folder / "20261121_100000_data.csv").write_bytes(b"a,b\n1,2\n")  # bytes: write_text would add CRLF on Windows
    (folder / "20261121_100000_summary.json").write_text('{"verdict": "ok", "duration_s": 61.0, "rows": 61}')

    overview = client.get("/api/garage").json()
    assert overview["cars"][0]["vin"] == vin and overview["cars"][0]["session_count"] == 1
    assert overview["cars"][0]["sessions"][0]["verdict"] == "ok"

    r = client.get(f"/api/garage/{vin}/20261121_100000_data.csv")
    assert r.status_code == 200 and r.text == "a,b\n1,2\n" and "attachment" in r.headers["content-disposition"]
    assert client.get(f"/api/garage/{vin}/car.json").status_code == 404  # only log files are downloadable
    assert client.get(f"/api/garage/{vin}/..%2Fcar.json").status_code == 404
    assert client.get("/api/garage/5NPE24AF3GH28308X/20261121_100000_data.csv").status_code == 404

    renamed = client.post(f"/api/garage/{vin}", json={"nickname": "Daily"})
    assert renamed.json()["display_name"] == "Daily"
    assert client.post("/api/garage/5NPE24AF9GH000002", json={"nickname": "x"}).status_code == 404
    assert client.post(f"/api/garage/{vin}", json={"nickname": "x" * 61}).status_code == 422


def test_demo_reports_a_car(client):
    client.post("/api/start", json={"demo": True})
    assert wait_for(lambda: client.get("/api/state").json()["info"] is not None)
    assert client.get("/api/state").json()["info"]["car"]["display_name"] == "2016 Hyundai Sonata"
    client.post("/api/stop")


def test_settings_roundtrip_and_validation(client, settings):
    body = client.get("/api/settings").json()
    assert body["thresholds"] == body["defaults"] and body["running"] is False
    assert {f["key"] for f in body["schema"]["thresholds"]} == set(body["defaults"])

    saved = client.put("/api/settings/thresholds", json={"values": {"coolant_warn_c": 99}}).json()
    assert saved["thresholds"]["coolant_warn_c"] == 99 and saved["defaults"]["coolant_warn_c"] == 102
    assert client.get("/api/settings").json()["thresholds"]["coolant_warn_c"] == 99

    bad = client.put("/api/settings/thresholds", json={"values": {"coolant_warn_c": 500, "nope": 1}})
    assert bad.status_code == 422 and len(bad.json()["detail"]) == 2
    assert client.get("/api/settings").json()["thresholds"]["coolant_warn_c"] == 99  # untouched by the bad request

    assert client.put("/api/settings/advanced", json={"values": {"beep": False}}).json()["advanced"]["beep"] is False
    assert client.put("/api/settings/advanced", json={"values": {"beep": 3}}).status_code == 422

    reset = client.post("/api/settings/reset", json={"scope": "all"}).json()
    assert reset["thresholds"] == reset["defaults"] and reset["advanced"] == reset["advanced_defaults"]
    assert client.post("/api/settings/reset", json={"scope": "bogus"}).status_code == 422


def test_per_car_limits_need_a_known_car(client, settings):
    from obd_dashboard.garage import Garage

    vin = "5NPE24AF3GH283081"
    assert client.put("/api/settings/thresholds", json={"values": {}, "vin": vin}).status_code == 404
    Garage(settings.output_dir).register(vin)
    r = client.put("/api/settings/thresholds", json={"values": {"fuel_low_pct": 25}, "vin": vin}).json()
    assert r["cars"][0]["vin"] == vin and r["cars"][0]["overrides"] == {"fuel_low_pct": 25}
    assert r["thresholds"]["fuel_low_pct"] == 10  # the global value did not move
    assert client.put("/api/settings/thresholds", json={"values": {}, "vin": "../etc"}).status_code == 404
    after = client.post("/api/settings/reset", json={"scope": "thresholds", "vin": vin}).json()
    assert after["cars"][0]["overrides"] == {}


def test_demo_uses_saved_limits(client):
    client.put("/api/settings/thresholds", json={"values": {"coolant_warn_c": 95, "fuel_low_pct": 12}})
    client.post("/api/start", json={"demo": True})
    assert wait_for(lambda: client.get("/api/state").json()["info"] is not None)
    assert client.get("/api/state").json()["info"]["thresholds"]["coolant_warn_c"] == 95
    client.post("/api/stop")


def test_history_endpoint(client, settings):
    from obd_dashboard.garage import Garage
    from tests.test_history import cold_drive, write_log

    garage = Garage(settings.output_dir)
    vin = "5NPE24AF3GH283081"
    garage.register(vin)
    write_log(garage.car_dir(vin) / "20261122_080000_data.csv", cold_drive(900))
    body = client.get(f"/api/history/{vin}").json()
    assert body["car"]["vin"] == vin and len(body["drives"]) == 1
    assert body["drives"][0]["coolant_max_c"] == 85.0
    assert client.get("/api/history/5NPE24AF9GH000002").status_code == 404  # valid shape, no such car
    assert client.get("/api/history/not-a-vin").status_code == 404
    assert client.get("/api/history/..%2F..%2Fetc").status_code == 404


def test_replayed_history_is_trimmed_by_time_and_carries_only_chart_values():
    from obd_dashboard import hub as hub_module

    class Quiet(hub_module.Hub):
        def _broadcast(self, kind, payload):  # no event loop in this test
            pass

    h = Quiet(Settings())
    for i in range(4000):  # 4 rows a second for 1000 s
        t = i / 4
        h.on_row({"t": t, "ts": "x", "values": {"RPM": 800.0, "INTAKE_TEMP": 20.0, "battery_v": 14.1}, "alerts": {},
                  "codes": {}, "misfire": {}, "misfire0": None, "warm": {}, "start_cool": None})  # fmt: skip
    history = h.snapshot()["history"]
    assert history[-1]["t"] - history[0]["t"] <= hub_module.HISTORY_SECONDS
    assert len(history) <= hub_module.HISTORY_ROWS
    assert history[0]["v"] == {"RPM": 800.0, "battery_v": 14.1}  # INTAKE_TEMP is only in `last`


# ---- used-car check ---------------------------------------------------------------
def test_hub_runs_a_check_instead_of_a_drive(settings):
    calls = []

    def fake_check(cfg, sink, stop):
        calls.append(cfg.com)
        sink.on_status("finished", "Check finished", {"check": {"verdict": "clear"}})

    hub = Hub(
        settings, session_factory=lambda *a: pytest.fail("a drive session must not start"), check_runner=fake_check
    )
    hub.start(port="COM9", mode="check")
    assert wait_for(lambda: hub.snapshot()["status"]["state"] == "finished")
    assert calls == ["COM9"] and hub.snapshot()["status"]["result"]["check"]["verdict"] == "clear"


def test_cancelled_check_goes_back_to_idle_not_to_a_drive_summary(settings):
    def slow_check(cfg, sink, stop):
        sink.on_status("checking", "Listening...")
        stop.wait(5)

    hub = Hub(settings, check_runner=slow_check)
    hub.start(mode="check")
    assert wait_for(lambda: hub.snapshot()["status"]["state"] == "checking")
    hub.end()
    hub.join(3)
    assert hub.snapshot()["status"] == {"state": "idle", "message": "Check cancelled", "mode": "check"}


def test_demo_check_through_the_api_and_its_files(client, hub, monkeypatch):
    import functools

    from obd_dashboard import hub as hub_module

    monkeypatch.setattr(hub_module, "run_demo_check", functools.partial(hub_module.run_demo_check, tick=0.01))
    assert client.post("/api/start", json={"demo": True, "mode": "check"}).status_code == 200
    assert wait_for(lambda: hub.snapshot()["status"]["state"] == "finished", timeout=5)
    check = client.get("/api/state").json()["status"]["result"]["check"]
    assert check["verdict"] == "flags" and check["files"] == {} and check["findings"] and check["demo"] is True


def test_start_rejects_an_unknown_mode(client):
    assert client.post("/api/start", json={"mode": "race"}).status_code == 422


def test_check_downloads_serve_only_real_check_files(client, settings):
    folder = settings.output_dir / "checks"
    folder.mkdir(parents=True)
    (folder / "20260102_030405_check.txt").write_text("report text")
    (settings.output_dir / "secret.txt").write_text("nope")
    ok = client.get("/api/checks/20260102_030405_check.txt")
    assert ok.status_code == 200 and ok.text == "report text"
    for bad in ("secret.txt", "..%2Fsecret.txt", "20260102_030405_check.exe", "20260102_999999_check.txt"):
        assert client.get(f"/api/checks/{bad}").status_code == 404
