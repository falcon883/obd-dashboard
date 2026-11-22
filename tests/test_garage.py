from __future__ import annotations

import json

import pytest

from obd_dashboard.garage import UNKNOWN_CAR, Garage
from obd_dashboard.vin import CarInfo

SONATA = "5NPE24AF3GH283081"
OTHER_SONATA = "5NPE24AF9GH000002"  # same model, different car


@pytest.fixture
def garage(tmp_path):
    return Garage(tmp_path / "logs")


def touch_session(garage, vin, stamp, *, summary=None, report=True):
    folder = garage.car_dir(vin)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stamp}_data.csv").write_text("a,b\n1,2\n")
    if report:
        (folder / f"{stamp}_report.txt").write_text("report")
    if summary is not None:
        (folder / f"{stamp}_summary.json").write_text(json.dumps(summary))


def test_register_creates_profile_with_offline_year_and_make(garage):
    car = garage.register(SONATA)
    assert (car.year, car.make, car.model) == (2016, "Hyundai", None)
    assert car.title == "2016 Hyundai" and car.display_name == "2016 Hyundai"
    assert (garage.car_dir(SONATA) / "car.json").exists()


def test_unreadable_vin_goes_to_unknown_car(garage):
    car = garage.register(None)
    assert car.vin == UNKNOWN_CAR and car.title == "Unknown car"
    assert garage.car_dir(None).name == UNKNOWN_CAR


def test_two_cars_of_the_same_model_stay_separate(garage):
    garage.register(SONATA)
    garage.register(OTHER_SONATA)
    touch_session(garage, SONATA, "20261121_214351")
    touch_session(garage, OTHER_SONATA, "20261122_080000")
    assert {c.vin for c in garage.cars()} == {SONATA, OTHER_SONATA}
    assert [s["stamp"] for s in garage.sessions(SONATA)] == ["20261121_214351"]
    assert [s["stamp"] for s in garage.sessions(OTHER_SONATA)] == ["20261122_080000"]


def test_apply_decode_nhtsa_beats_the_offline_guess_but_never_the_nickname(garage):
    car = garage.register(SONATA)
    car.make = "Guess"
    garage.save(car)
    garage.rename(SONATA, "Daily")
    decoded = CarInfo(SONATA, 2016, "Hyundai", "Sonata", None, "2.4 L 4-cyl", "nhtsa")
    car = garage.apply_decode(car, decoded)  # `car` is stale: nickname was set after it was loaded
    assert (car.make, car.model, car.engine, car.source) == ("Hyundai", "Sonata", "2.4 L 4-cyl", "nhtsa")
    assert car.nickname == "Daily" and car.display_name == "Daily" and car.title == "2016 Hyundai Sonata"
    assert garage.load(SONATA).nickname == "Daily"


def test_hand_edited_profiles_are_left_alone(garage):
    car = garage.register(SONATA)
    car.model, car.source = "Sonata SE (mine)", "manual"
    garage.save(car)
    out = garage.apply_decode(car, CarInfo(SONATA, 2016, "Hyundai", "Sonata", None, "2.4 L 4-cyl", "nhtsa"))
    assert out.model == "Sonata SE (mine)" and out.engine is None and out.source == "manual"


def test_offline_decode_only_fills_blanks(garage):
    car = garage.register(SONATA)
    out = garage.apply_decode(car, CarInfo(SONATA, 1999, "Other", "X", None, None, "vin"))
    assert (out.year, out.make, out.model) == (2016, "Hyundai", "X")


def test_register_again_keeps_user_edits(garage):
    garage.register(SONATA)
    garage.rename(SONATA, "Daily")
    assert garage.register(SONATA).nickname == "Daily"


def test_rename_validates_the_key_and_trims(garage):
    garage.register(SONATA)
    assert garage.rename(SONATA, "  " + "x" * 80).nickname == "x" * 60
    assert garage.rename("../etc", "x") is None
    assert garage.rename(OTHER_SONATA, "x") is None  # not in the garage


def test_cars_sorted_by_last_seen_and_ignore_junk_folders(garage):
    a, b = garage.register(SONATA), garage.register(OTHER_SONATA)
    a.last_seen = "2020-01-01T00:00:00"
    garage.save(a)
    (garage.root / "not-a-vin").mkdir()
    (garage.root / "not-a-vin" / "car.json").write_text("{}")
    assert [c.vin for c in garage.cars()] == [b.vin, a.vin]


def test_sessions_newest_first_with_summary_and_crashed_sessions(garage):
    garage.register(SONATA)
    touch_session(garage, SONATA, "20261121_100000", summary={"duration_s": 60.0, "verdict": "ok", "rows": 60})
    touch_session(garage, SONATA, "20261121_200000", report=False)  # crashed: no summary, no report
    first, second = garage.sessions(SONATA)
    assert first["stamp"] == "20261121_200000" and first["complete"] is False and "report" not in first["files"]
    assert second["complete"] is True and second["verdict"] == "ok" and second["files"]["summary"].endswith(".json")


def test_corrupt_summary_does_not_break_listing(garage):
    touch_session(garage, SONATA, "20261121_100000")
    (garage.car_dir(SONATA) / "20261121_100000_summary.json").write_text("{not json")
    assert garage.sessions(SONATA)[0]["complete"] is False


@pytest.mark.parametrize(
    ("key", "name"),
    [
        (SONATA, "../car.json"),
        (SONATA, "car.json"),
        (SONATA, "20261121_100000_data.csv/../../x"),
        ("..", "20261121_100000_data.csv"),
        ("5NPE24AF3GH28308", "20261121_100000_data.csv"),  # malformed VIN
        (OTHER_SONATA, "20261121_100000_data.csv"),  # nonexistent car
    ],
)
def test_file_path_refuses_anything_unexpected(garage, key, name):
    touch_session(garage, SONATA, "20261121_100000")
    assert garage.file_path(key, name) is None


def test_file_path_serves_known_files(garage):
    touch_session(garage, SONATA, "20261121_100000")
    assert garage.file_path(SONATA, "20261121_100000_data.csv").read_text() == "a,b\n1,2\n"


def test_legacy_flat_logs_are_reported_as_unsorted(garage):
    garage.root.mkdir(parents=True)
    (garage.root / "obd_20261121_214351_data.csv").write_text("x")
    assert garage.unsorted() == ["obd_20261121_214351_data.csv"]
    assert garage.overview()["cars"] == []


def test_overview_shape(garage):
    garage.register(SONATA)
    touch_session(garage, SONATA, "20261121_100000")
    (car,) = garage.overview()["cars"]
    assert car["vin"] == SONATA and car["session_count"] == 1 and car["display_name"] == "2016 Hyundai"
