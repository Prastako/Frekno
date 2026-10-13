"""Tests for pipeline.transit (weekend departures per stop from GTFS)."""

import json
import zipfile
from datetime import date

import pandas as pd

from pipeline import transit

DAYS = transit.weekend(date(2026, 10, 13))


def gtfs(path, stops, trips, times, calendar=None, dates=None):
    """Write a small GTFS zip. times rows: (trip_id, departure_time, stop_id, stop_sequence, pickup_type)."""
    files = {
        "stops.txt": pd.DataFrame(stops, columns=["stop_id", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station"]),
        "trips.txt": pd.DataFrame(trips, columns=["trip_id", "service_id"]),
        "stop_times.txt": pd.DataFrame(times, columns=["trip_id", "departure_time", "stop_id", "stop_sequence", "pickup_type"]),
    }
    if calendar is not None:
        cols = ["service_id", *transit._WEEKDAYS, "start_date", "end_date"]
        files["calendar.txt"] = pd.DataFrame(calendar, columns=cols)
    if dates is not None:
        files["calendar_dates.txt"] = pd.DataFrame(dates, columns=["service_id", "date", "exception_type"])
    with zipfile.ZipFile(path, "w") as z:
        for name, df in files.items():
            z.writestr(name, df.to_csv(index=False))
    return path


def feeds(tmp_path):
    stops1 = [("A", "Lhota,náves", "49.8", "15.0", "0", ""), ("B", "Lhota,náves", "49.8", "15.0", "0", ""),
              ("ST", "Lhota", "49.9", "15.1", "1", ""), ("ST1", "Lhota", "49.9001", "15.1001", "0", "ST"),
              ("Z", "Paris", "0", "0", "0", "")]
    trips1 = [("T1", "FR"), ("T2", "WE"), ("T3", "WE"), ("T4", "FR"), ("T5", "WE")]
    times1 = [("T1", "24:30:00", "A", "1", "0"), ("T1", "24:40:00", "B", "2", "0"),
              ("T2", "05:10:00", "A", "1", "0"), ("T2", "05:40:00", "ST1", "2", "0"), ("T2", "06:00:00", "A", "3", "0"),
              ("T3", "01:15:00", "A", "1", "1"), ("T3", "01:20:00", "B", "2", "0"), ("T3", "02:00:00", "ST1", "3", "0"),
              ("T4", "23:50:00", "ST1", "1", "0"), ("T4", "23:59:00", "A", "2", "0"),
              ("T5", "02:00:00", "Z", "1", "0"), ("T5", "02:30:00", "A", "2", "0")]
    cal = [("FR", "0", "0", "0", "0", "1", "0", "0", "20260101", "20261231"),
           ("WE", "0", "0", "0", "0", "0", "1", "1", "20260101", "20261231")]
    f1 = gtfs(tmp_path / "f1.zip", stops1, trips1, times1, calendar=cal)
    stops2 = [("N1", "Lhota", "49.9", "15.1", "0", ""), ("N2", "Dolní Lhota", "49.95", "15.2", "0", "")]
    times2 = [("R1", "03:30:00", "N1", "1", "0"), ("R1", "03:50:00", "N2", "2", "0")]
    f2 = gtfs(tmp_path / "f2.zip", stops2, [("R1", "D17")], times2, dates=[("D17", "20261017", "1")])
    return [f1, f2]


def test_weekend():
    assert DAYS == [date(2026, 10, 16), date(2026, 10, 17), date(2026, 10, 18)]
    assert transit.weekend(date(2026, 10, 16)) == DAYS
    assert transit.weekend(date(2026, 10, 17))[0] == date(2026, 10, 23)


def test_minutes():
    assert transit.minutes(pd.Series(["7:05:00", "24:30:00", "00:00:00"])).tolist() == [425, 1470, 0]


def test_active_services(tmp_path):
    cal = [("WE", "0", "0", "0", "0", "0", "1", "1", "20260101", "20261231"),
           ("FR", "0", "0", "0", "0", "1", "0", "0", "20260101", "20261231")]
    exc = [("X", "20261017", "1"), ("WE", "20261018", "2")]
    path = gtfs(tmp_path / "c.zip", [], [], [], calendar=cal, dates=exc)
    with zipfile.ZipFile(path) as z:
        assert transit.active_services(z, DAYS) == [{"FR"}, {"WE", "X"}, set()]


def test_build_stops(tmp_path):
    res = transit.build_stops(feeds(tmp_path), date(2026, 10, 13))
    assert res["nights"] == ["2026-10-16", "2026-10-17", "2026-10-18"]
    assert (res["source"], res["built"], res["license"]) == ("JrUtil", "2026-10-13", transit.LICENSE)
    x1, y1 = transit._TO_SJTSK.transform(15.1, 49.9)
    x2, y2 = transit._TO_SJTSK.transform(15.0, 49.8)
    assert res["stops"] == [[round(x1), round(y1), "Lhota", 210, 340, -1, 340],
                            [round(x2), round(y2), "Lhota,náves", 80, 310, 80, 310]]


def test_main_writes_the_stops_file(tmp_path, monkeypatch, capsys):
    src = dict(zip(transit.FEEDS, feeds(tmp_path)))

    def fake_download(url, dest, **kw):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src[url.rsplit("/", 1)[1]].read_bytes())

    monkeypatch.setattr(transit, "download", fake_download)
    out = tmp_path / "site" / "stops.json"
    assert transit.main([str(out), "--feeds-dir", str(tmp_path / "feeds"), "--day", "2026-10-13"]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [s[2] for s in data["stops"]] == ["Lhota", "Lhota,náves"]
    assert json.loads(capsys.readouterr().out)["stops"] == 2