"""FastAPI app: REST endpoints, the SSE stream, and the built React UI as static files."""

from __future__ import annotations

import asyncio
import json
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from serial.tools import list_ports

from obd_dashboard.garage import Garage
from obd_dashboard.hub import Hub, SessionBusy
from obd_dashboard.settings import Settings

BUNDLED_UI = Path(__file__).parent / "static"
PING_EVERY = 15.0
NOT_BUILT = (
    "<h1>Dashboard UI not built</h1><p>In the <code>frontend</code> folder run "
    "<code>npm install</code> then <code>npm run build</code>.</p>"
)


class StartRequest(BaseModel):
    port: Optional[str] = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_./-]+$")
    baud: int = Field(default=0, ge=0, le=2_000_000, description="0 = auto-detect")
    demo: bool = False


class Ack(BaseModel):
    ok: bool = True
    message: str = ""


class RenameRequest(BaseModel):
    nickname: str = Field(max_length=60)


class PortInfo(BaseModel):
    device: str
    description: str = ""


async def event_stream(
    hub: Hub,
    is_disconnected: Callable[[], Awaitable[bool]],
    ping_every: float = PING_EVERY,
) -> AsyncIterator[str]:
    """Server-Sent Events: a full snapshot first, then live updates, with keep-alive pings."""
    queue = hub.subscribe()
    try:
        yield f"event: snapshot\ndata: {json.dumps(hub.snapshot())}\n\n"
        while not await is_disconnected():
            try:
                yield await asyncio.wait_for(queue.get(), timeout=ping_every)
            except asyncio.TimeoutError:
                if not hub.is_subscribed(queue):  # dropped for being too slow: let the browser resync
                    return
                yield ": ping\n\n"
    finally:
        hub.unsubscribe(queue)


def create_app(settings: Settings, hub: Optional[Hub] = None) -> FastAPI:
    hub = hub or Hub(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        hub.attach_loop(asyncio.get_running_loop())
        if settings.demo or settings.autostart:
            hub.start(port=settings.com, baud=settings.baud, demo=settings.demo)
        if settings.open_browser:
            threading.Timer(1.0, webbrowser.open, args=(f"http://localhost:{settings.http_port}",)).start()
        yield
        hub.end()  # let the logger finish its report before the process exits
        await asyncio.to_thread(hub.join, 8)

    # No CORS middleware on purpose: the UI is served from this same origin (and the Vite dev
    # server proxies /api), so other websites cannot start or stop your logger.
    app = FastAPI(title="OBD Dashboard", version="1.0.0", lifespan=lifespan)
    app.state.hub = hub

    @app.get("/api/state")
    def state() -> Dict[str, Any]:
        return hub.snapshot()

    @app.get("/api/ports", response_model=List[PortInfo])
    def ports() -> List[PortInfo]:
        return [PortInfo(device=p.device, description=p.description or "") for p in list_ports.comports()]

    @app.post("/api/start", response_model=Ack)
    def start(req: StartRequest) -> Ack:
        try:
            hub.start(port=req.port, baud=req.baud, demo=req.demo)
        except SessionBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Ack(message="started")

    @app.post("/api/stop", response_model=Ack)
    def stop() -> Ack:
        hub.end()
        return Ack()

    garage = Garage(settings.output_dir)

    @app.get("/api/garage")
    def garage_overview() -> Dict[str, Any]:
        return garage.overview()

    @app.post("/api/garage/{vin}")
    def garage_rename(vin: str, req: RenameRequest) -> Dict[str, Any]:
        car = garage.rename(vin, req.nickname)
        if car is None:
            raise HTTPException(status_code=404, detail="Unknown car")
        return car.to_dict()

    @app.get("/api/garage/{vin}/{name}")
    def garage_file(vin: str, name: str) -> FileResponse:
        path = garage.file_path(vin, name)  # validated: known car folder + known file-name shape only
        if path is None:
            raise HTTPException(status_code=404, detail="No such file")
        return FileResponse(path, filename=name)

    @app.get("/api/stream")
    async def stream(request: Request) -> StreamingResponse:
        return StreamingResponse(
            event_stream(hub, request.is_disconnected),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    ui = settings.static_dir or BUNDLED_UI
    if (ui / "index.html").exists():
        app.mount("/", StaticFiles(directory=ui, html=True), name="ui")
    else:

        @app.get("/", response_class=HTMLResponse)
        def not_built() -> str:
            return NOT_BUILT

    return app
