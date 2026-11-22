"""All runtime configuration in one place (no module-level mutable globals)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Tuning:
    """Polling behaviour. Tests shrink these so a session runs in milliseconds."""

    extra_per_loop: int = 4  # slower sensors refreshed per loop (round-robin)
    slow_every: float = 60.0  # seconds between trouble-code + misfire-counter checks
    target_loop: float = 1.0  # seconds per CSV row
    lost_after: int = 15  # empty loops in a row before the link/engine is considered gone
    reconnect_tries: int = 3
    reconnect_wait: float = 5.0  # seconds between reconnect attempts


@dataclass(frozen=True)
class Settings:
    # web server
    host: str = "127.0.0.1"
    http_port: int = 8000
    open_browser: bool = True
    static_dir: Optional[Path] = None  # None -> the bundled frontend build
    # session
    com: Optional[str] = None  # None -> auto-detect
    baud: int = 0  # 0 -> auto-detect
    demo: bool = False
    autostart: bool = False
    beep: bool = True
    lookup_vin: bool = True  # ask NHTSA (free, needs internet) for make/model; only the VIN is sent
    output_dir: Path = Path("logs")  # the garage: one sub-folder per car (by VIN)
    tuning: Tuning = field(default_factory=Tuning)
