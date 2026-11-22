"""VIN helpers: offline decoding (year, make) and an optional NHTSA lookup (model, engine)."""

from __future__ import annotations

import datetime
import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # I, O and Q are never used in a VIN
NHTSA_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"

# Position 10 of the VIN encodes the model year, repeating every 30 years (U, Z and 0 are unused).
YEAR_CODES = "ABCDEFGHJKLMNPRSTVWXY123456789"

# World manufacturer identifier (first 3 characters) -> make. Not exhaustive: NHTSA fills in the rest.
WMI_MAKES: Dict[str, str] = {
    "5NP": "Hyundai", "5NM": "Hyundai", "KMH": "Hyundai", "KMJ": "Hyundai", "2HM": "Hyundai",
    "5XY": "Kia", "KNA": "Kia", "KND": "Kia", "KNM": "Kia", "3KP": "Kia",
    "1HG": "Honda", "2HG": "Honda", "JHM": "Honda", "19X": "Honda", "5FN": "Honda", "5J6": "Honda", "SHH": "Honda",
    "4T1": "Toyota", "2T1": "Toyota", "JTD": "Toyota", "JT2": "Toyota", "5YF": "Toyota", "JTM": "Toyota",
    "1N4": "Nissan", "JN1": "Nissan", "3N1": "Nissan", "5N1": "Nissan", "JN8": "Nissan",
    "1FA": "Ford", "1FT": "Ford", "1FM": "Ford", "3FA": "Ford", "1FD": "Ford",
    "1G1": "Chevrolet", "1GC": "Chevrolet", "3G1": "Chevrolet", "1GT": "GMC", "1G4": "Buick",
    "1C4": "Chrysler", "1C3": "Chrysler", "2C3": "Chrysler", "1J4": "Jeep", "3C4": "Chrysler",
    "JM1": "Mazda", "JM3": "Mazda", "4S3": "Subaru", "JF1": "Subaru", "JF2": "Subaru", "4S4": "Subaru",
    "3VW": "Volkswagen", "WVW": "Volkswagen", "1VW": "Volkswagen",
    "WBA": "BMW", "WBY": "BMW", "5UX": "BMW", "WDD": "Mercedes-Benz", "WDB": "Mercedes-Benz",
    "W1K": "Mercedes-Benz", "WAU": "Audi", "5YJ": "Tesla", "7SA": "Tesla", "YV1": "Volvo",
    "JTH": "Lexus", "2HN": "Acura", "19U": "Acura", "SAL": "Land Rover", "ZAR": "Alfa Romeo",
}  # fmt: skip


def normalize_vin(text: Any) -> Optional[str]:
    """Upper-cased VIN if `text` is a well-formed 17-character VIN, else None."""
    if not isinstance(text, str):
        return None
    vin = text.strip().upper()
    return vin if VIN_RE.match(vin) else None


def model_year(vin: str, this_year: Optional[int] = None) -> Optional[int]:
    """Decode VIN position 10. North American VINs disambiguate the 30-year cycle with position 7."""
    code = vin[9]
    if code not in YEAR_CODES:
        return None
    this_year = this_year or datetime.date.today().year
    base = 1980 + YEAR_CODES.index(code)  # 1980..2009
    if vin[0] in "12345":  # US/Canada/Mexico: letter in position 7 means 2010 or later
        return base + 30 if vin[6].isalpha() else base
    # elsewhere the rule varies: take the newest year that is not in the future
    return base + 30 if base + 30 <= this_year + 1 else base


@dataclass
class CarInfo:
    vin: str
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    engine: Optional[str] = None
    source: str = "vin"  # "vin" (offline) or "nhtsa"


def decode_offline(vin: str) -> CarInfo:
    """Year and make straight from the VIN - works with no internet."""
    return CarInfo(vin=vin, year=model_year(vin), make=WMI_MAKES.get(vin[:3]), source="vin")


def _http_get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "obd-dashboard"})  # noqa: S310 - fixed https URL
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        data: bytes = resp.read()
        return data


def _clean(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text if text and text.lower() != "not provided" else None


def decode_nhtsa(
    vin: str,
    fetch: Callable[[str, float], bytes] = _http_get,
    timeout: float = 4.0,
) -> Optional[CarInfo]:
    """Look the VIN up in NHTSA's free vPIC database. None when offline or not found.

    Only the VIN is sent. Failures are silent: the app works the same without a result.
    """
    try:
        payload = json.loads(fetch(NHTSA_URL.format(vin=vin), timeout))
        row = payload["Results"][0]
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        log.info("VIN lookup skipped (%s: %s)", type(exc).__name__, exc)
        return None
    make, model = _clean(row.get("Make")), _clean(row.get("Model"))
    if not make or not model:
        return None
    year = _clean(row.get("ModelYear"))
    trim = _clean(row.get("Trim"))
    cyl, disp = _clean(row.get("EngineCylinders")), _clean(row.get("DisplacementL"))
    engine = None
    if disp and cyl:
        try:
            engine = f"{float(disp):.1f} L {int(float(cyl))}-cyl"
        except ValueError:
            engine = None
    return CarInfo(
        vin=vin,
        year=int(year) if year and year.isdigit() else model_year(vin),
        make=make.title() if make.isupper() and len(make) > 3 else make,
        model=model,
        trim=None if trim and "/" in trim else trim,  # NHTSA lists every trim sharing a VIN pattern
        engine=engine,
        source="nhtsa",
    )
