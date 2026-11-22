from __future__ import annotations

import json
import urllib.error

import pytest

from obd_dashboard import vin as v

SONATA = "5NPE24AF3GH283081"


def test_normalize_vin():
    assert v.normalize_vin(" 5npe24af3gh283081 ") == SONATA
    assert v.normalize_vin("5NPE24AF3GH28308") is None  # 16 chars (the python-obd truncation bug)
    assert v.normalize_vin("5NPE24AF3GH28308I") is None  # 'I' is never valid
    assert v.normalize_vin(None) is None and v.normalize_vin(b"x") is None


@pytest.mark.parametrize(
    ("vin", "year"),
    [
        (SONATA, 2016),  # 'G', letter in position 7 -> 2010+ cycle
        ("1HGCM82633A004352", 2003),  # '3', digit in position 7 -> 1980-2009 cycle
        ("1M8GDM9AXKP042781", 1989),  # 'K', digit in position 7 -> 1980-2009 cycle
        ("WBA3A5C51CF256651", 2012),  # non-US: newest year not in the future
    ],
)
def test_model_year(vin, year):
    assert v.model_year(vin, this_year=2026) == year


def test_model_year_invalid_code():
    assert v.model_year("5NPE24AF3UH283081") is None  # 'U' is not a year code


def test_offline_decode_gives_year_and_make():
    info = v.decode_offline(SONATA)
    assert (info.year, info.make, info.model, info.source) == (2016, "Hyundai", None, "vin")
    assert v.decode_offline("ZZZ" + SONATA[3:]).make is None


NHTSA_OK = {
    "Results": [
        {
            "Make": "HYUNDAI", "Model": "Sonata", "ModelYear": "2016", "DisplacementL": "2.4000000000",
            "EngineCylinders": "4", "Trim": "SE / SE w/Popular Pkg / Eco / Eco w/Tech Pkg",
        }
    ]
}  # fmt: skip


def test_nhtsa_decode_success_and_url():
    seen = []

    def fetch(url, timeout):
        seen.append((url, timeout))
        return json.dumps(NHTSA_OK).encode()

    info = v.decode_nhtsa(SONATA, fetch=fetch, timeout=3)
    assert (info.year, info.make, info.model, info.engine, info.source) == (
        2016,
        "Hyundai",
        "Sonata",
        "2.4 L 4-cyl",
        "nhtsa",
    )
    assert info.trim is None  # ambiguous multi-trim string is not shown
    assert seen == [(v.NHTSA_URL.format(vin=SONATA), 3)]


@pytest.mark.parametrize(
    "fetch",
    [
        lambda *_: (_ for _ in ()).throw(urllib.error.URLError("offline")),
        lambda *_: (_ for _ in ()).throw(TimeoutError()),
        lambda *_: b"<html>not json</html>",
        lambda *_: b'{"Results": []}',
        lambda *_: json.dumps({"Results": [{"Make": "", "Model": ""}]}).encode(),
    ],
)
def test_nhtsa_failures_are_silent(fetch):
    assert v.decode_nhtsa(SONATA, fetch=fetch) is None
