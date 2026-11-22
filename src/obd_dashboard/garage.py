"""The garage: one folder per car (keyed by VIN) holding that car's profile and every session's files.

    logs/
      <VIN>/
        car.json                        profile (year, make, model, nickname, ...)
        20261121_214351_data.csv        one row per second, every sensor
        20261121_214351_report.txt      human-readable report
        20261121_214351_summary.json    machine-readable summary (verdict, duration, ...)

Two cars of the same model never mix because the VIN is unique. If the VIN cannot be read the
session goes to `logs/unknown-car/`.
"""

from __future__ import annotations

import datetime
import json
import re
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from obd_dashboard.vin import VIN_RE, CarInfo, decode_offline

UNKNOWN_CAR = "unknown-car"
FILE_RE = re.compile(r"^\d{8}_\d{6}_(data\.csv|report\.txt|summary\.json)$")
VERDICTS = {0: "ok", 1: "warn", 2: "crit"}


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


@dataclass
class Car:
    vin: str  # 17-character VIN, or UNKNOWN_CAR
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    engine: Optional[str] = None
    nickname: str = ""
    source: str = "vin"
    first_seen: str = field(default_factory=_now)
    last_seen: str = field(default_factory=_now)

    @property
    def title(self) -> str:
        """'2016 Hyundai Sonata' - whatever is known, never empty."""
        parts = [str(self.year) if self.year else None, self.make, self.model]
        return " ".join(p for p in parts if p) or "Unknown car"

    @property
    def display_name(self) -> str:
        return self.nickname or self.title

    def to_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "title": self.title, "display_name": self.display_name}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Car:
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class Garage:
    def __init__(self, root: Path) -> None:
        self.root = root

    # ---- cars ------------------------------------------------------------------------------
    @staticmethod
    def valid_key(key: str) -> bool:
        return key == UNKNOWN_CAR or bool(VIN_RE.match(key))

    def car_dir(self, vin: Optional[str]) -> Path:
        return self.root / (vin or UNKNOWN_CAR)

    def load(self, vin: str) -> Optional[Car]:
        path = self.car_dir(vin) / "car.json"
        try:
            return Car.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return None

    def save(self, car: Car) -> None:
        folder = self.car_dir(car.vin)
        folder.mkdir(parents=True, exist_ok=True)
        _atomic_write(folder / "car.json", json.dumps(asdict(car), indent=2) + "\n")

    def register(self, vin: Optional[str]) -> Car:
        """Find or create this car's profile and mark it as seen now. Never overwrites user edits."""
        key = vin or UNKNOWN_CAR
        car = self.load(key)
        if car is None:
            offline = decode_offline(vin) if vin else CarInfo(vin=UNKNOWN_CAR)
            car = Car(vin=key, year=offline.year, make=offline.make, source=offline.source)
        car.last_seen = _now()
        self.save(car)
        return car

    def apply_decode(self, car: Car, decoded: CarInfo) -> Car:
        """Merge a lookup result. NHTSA is authoritative over the offline guess; hand-edited profiles
        (`"source": "manual"` in car.json) and the nickname are never touched."""
        car = self.load(car.vin) or car  # pick up a nickname typed while the session was running
        if car.source != "manual":
            authoritative = decoded.source == "nhtsa"
            for name in ("year", "make", "model", "trim", "engine"):
                new = getattr(decoded, name)
                if new and (authoritative or getattr(car, name) in (None, "")):
                    setattr(car, name, new)
            if authoritative:
                car.source = "nhtsa"
        self.save(car)
        return car

    def rename(self, key: str, nickname: str) -> Optional[Car]:
        car = self.load(key) if self.valid_key(key) else None
        if car is None:
            return None
        car.nickname = nickname.strip()[:60]
        self.save(car)
        return car

    def cars(self) -> List[Car]:
        found = []
        if self.root.is_dir():
            for folder in self.root.iterdir():
                car = self.load(folder.name) if folder.is_dir() and self.valid_key(folder.name) else None
                if car is not None:
                    found.append(car)
        return sorted(found, key=lambda c: c.last_seen, reverse=True)

    # ---- sessions --------------------------------------------------------------------------
    def sessions(self, key: str) -> List[Dict[str, Any]]:
        """Newest first. Uses summary.json when present; a crashed session still shows up from its CSV."""
        folder = self.car_dir(key)
        out: List[Dict[str, Any]] = []
        for csv_path in sorted(folder.glob("*_data.csv"), reverse=True):
            stamp = csv_path.name[: -len("_data.csv")]
            files = {"csv": csv_path.name}
            report, summary = folder / f"{stamp}_report.txt", folder / f"{stamp}_summary.json"
            if report.exists():
                files["report"] = report.name
            info: Dict[str, Any] = {"stamp": stamp, "complete": False, "bytes": csv_path.stat().st_size}
            if summary.exists():
                files["summary"] = summary.name
                with suppress(OSError, ValueError):
                    info.update(json.loads(summary.read_text(encoding="utf-8")), complete=True)
            info["files"] = files
            out.append(info)
        return out

    def unsorted(self) -> List[str]:
        """Logs from before the garage existed (flat files directly in the root folder)."""
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.glob("obd_*") if p.is_file())

    def file_path(self, key: str, name: str) -> Optional[Path]:
        """Safe lookup for downloads: only a known car folder and a known file-name shape."""
        if not (self.valid_key(key) and FILE_RE.match(name)):
            return None
        path = self.car_dir(key) / name
        return path if path.is_file() else None

    def overview(self) -> Dict[str, Any]:
        cars = []
        for car in self.cars():
            sessions = self.sessions(car.vin)
            cars.append({**car.to_dict(), "sessions": sessions, "session_count": len(sessions)})
        return {"cars": cars, "unsorted": self.unsorted(), "folder": str(self.root.resolve())}
