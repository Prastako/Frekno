"""Public transport for the website: stops with their night and morning departures at the weekend (JrUtil GTFS).

Each stop gets, for the nights Friday to Saturday and Saturday to Sunday, its last departure between midnight
and 04:00 and its first departure between 04:00 and noon. The website finds the nearest stop to a spot itself.
"""

import argparse
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

from pipeline.fetch.download import download

JRUTIL_URL = "https://data.jr.ggu.cz/results/latest/"
FEEDS = ["JDF_merged_GTFS.zip", "CZPTT_GTFS.zip"]
NIGHT_END = 240  # minutes after midnight: departures until 04:00 are night departures
MORNING_END = 720  # the morning lasts until noon
GROUP_M = 300  # stops with the same name in one 300 m cell are one stop on the website
BBOX = (12.0, 48.5, 18.9, 51.1)  # lon/lat box around Czechia
ATTRIBUTION = ("JrUtil (https://data.jr.ggu.cz/), timetables from CIS JŘ. Stop positions: OpenStreetMap contributors "
               "(ODbL); open data of Ostrava (datový podklad © Statutární město Ostrava), Most and the Liberec Region "
               "(CC BY-SA 4.0); open data of the Moravian-Silesian Region, Brno and PID (CC BY 4.0); open data of the "
               "South Bohemian Region (CC0); further sources collected in jrunify-ext-geodata.")
LICENSE = "Shared under the terms of its sources: ODbL 1.0 and CC BY-SA 4.0."
_TO_SJTSK = Transformer.from_crs("EPSG:4326", "EPSG:5514", always_xy=True)
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def weekend(day: date) -> list[date]:
    """Friday, Saturday and Sunday of the first weekend whose Friday is *day* or later."""
    fri = day + timedelta(days=(4 - day.weekday()) % 7)
    return [fri + timedelta(days=i) for i in range(3)]


def _read(z: zipfile.ZipFile, name: str, **kw) -> pd.DataFrame:
    if name not in z.namelist():
        return pd.DataFrame()
    with z.open(name) as f:
        return pd.read_csv(f, dtype=str, keep_default_na=False, **kw)


def active_services(z: zipfile.ZipFile, days: list[date]) -> list[set[str]]:
    """Service ids running on each of *days* (calendar.txt patterns plus calendar_dates.txt exceptions)."""
    cal, exc = _read(z, "calendar.txt"), _read(z, "calendar_dates.txt")
    out = []
    for d in days:
        key = d.strftime("%Y%m%d")
        on = set()
        if len(cal):
            on = set(cal.loc[(cal[_WEEKDAYS[d.weekday()]] == "1") & (cal["start_date"] <= key) & (cal["end_date"] >= key), "service_id"])
        if len(exc):
            e = exc[exc["date"] == key]
            on = (on | set(e.loc[e["exception_type"] == "1", "service_id"])) - set(e.loc[e["exception_type"] == "2", "service_id"])
        out.append(on)
    return out


def minutes(times: pd.Series) -> np.ndarray:
    """Minutes after midnight of the service day for GTFS times (H:MM:SS; hours may pass 24)."""
    hm = times.str.split(":", n=2, expand=True)
    return hm[0].astype(int).to_numpy() * 60 + hm[1].astype(int).to_numpy()


def feed_departures(path, days: list[date], chunk: int = 1_000_000) -> pd.DataFrame:
    """Departures (stop_id, m = minutes after Friday 00:00) between midnight and noon on Saturday and Sunday.

    A departure is a stop time with a departure time, open for boarding (pickup_type not 1), that is not the last
    stop of its trip.
    """
    with zipfile.ZipFile(path) as z:
        services = active_services(z, days)
        trips = _read(z, "trips.txt", usecols=["trip_id", "service_id"])
        runs = pd.concat([pd.DataFrame({"trip_id": trips.loc[trips["service_id"].isin(s), "trip_id"], "base": i * 1440})
                          for i, s in enumerate(services)], ignore_index=True)
        wanted = set(runs["trip_id"])
        parts, last = [], []
        with z.open("stop_times.txt") as f:
            cols = ["trip_id", "departure_time", "stop_id", "stop_sequence", "pickup_type"]
            for ch in pd.read_csv(f, dtype=str, keep_default_na=False, usecols=cols, chunksize=chunk):
                ch = ch[ch["trip_id"].isin(wanted)]
                if ch.empty:
                    continue
                seq = ch["stop_sequence"].astype(int)
                last.append(seq.groupby(ch["trip_id"]).max())
                ch = ch.assign(seq=seq)[(ch["pickup_type"] != "1") & (ch["departure_time"] != "")]
                if ch.empty:
                    continue
                ch = ch.assign(t=minutes(ch["departure_time"])).merge(runs, on="trip_id")
                m = ch["base"] + ch["t"]
                ch = ch.assign(m=m)[((m >= 1440) & (m < 1440 + MORNING_END)) | ((m >= 2880) & (m < 2880 + MORNING_END))]
                parts.append(ch[["trip_id", "stop_id", "seq", "m"]])
    if not parts:
        return pd.DataFrame({"stop_id": pd.Series(dtype=str), "m": pd.Series(dtype=int)})
    dep = pd.concat(parts, ignore_index=True)
    final = pd.concat(last).groupby(level=0).max()
    dep = dep[dep["seq"] < dep["trip_id"].map(final).to_numpy()]
    return dep[["stop_id", "m"]].reset_index(drop=True)


def feed_stops(path) -> pd.DataFrame:
    """Stops of one GTFS zip with the name and position used on the website (a platform takes its station's)."""
    with zipfile.ZipFile(path) as z:
        s = _read(z, "stops.txt", usecols=["stop_id", "stop_name", "stop_lat", "stop_lon", "parent_station"])
    pos = s.set_index("stop_id")
    parent = s["parent_station"].where(s["parent_station"].isin(pos.index) & (s["parent_station"] != ""), s["stop_id"])
    out = pd.DataFrame({"stop_id": s["stop_id"], "name": pos.loc[parent, "stop_name"].to_numpy(),
                        "lon": pd.to_numeric(pos.loc[parent, "stop_lon"].to_numpy(), errors="coerce"),
                        "lat": pd.to_numeric(pos.loc[parent, "stop_lat"].to_numpy(), errors="coerce")})
    lo0, la0, lo1, la1 = BBOX
    return out[out["lon"].between(lo0, lo1) & out["lat"].between(la0, la1)].reset_index(drop=True)


def build_stops(feeds: list, day: date) -> dict:
    """The website's stops file for the weekend of *day*: per stop x, y (EPSG:5514), name and, for each night,
    the last departure after midnight and the first in the morning (minutes after midnight, -1 for none)."""
    days = weekend(day)
    deps, stops = [], []
    for k, path in enumerate(feeds):
        d, s = feed_departures(path, days), feed_stops(path)
        deps.append(d.assign(stop_id=f"{k}:" + d["stop_id"]))
        stops.append(s.assign(stop_id=f"{k}:" + s["stop_id"]))
    dep = pd.concat(deps, ignore_index=True).merge(pd.concat(stops, ignore_index=True), on="stop_id")
    x, y = _TO_SJTSK.transform(dep["lon"].to_numpy(), dep["lat"].to_numpy())
    dep = dep.assign(x=x, y=y, gx=np.floor(x / GROUP_M), gy=np.floor(y / GROUP_M))
    rows = []
    for (name, _, _), g in dep.groupby(["name", "gx", "gy"], sort=True):
        vals = []
        for base in (1440, 2880):
            m = g["m"].to_numpy() - base
            night, morning = m[(m >= 0) & (m < NIGHT_END)], m[(m >= NIGHT_END) & (m < MORNING_END)]
            vals += [int(night.max()) if len(night) else -1, int(morning.min()) if len(morning) else -1]
        rows.append([int(round(g["x"].mean())), int(round(g["y"].mean())), name, *vals])
    return {"source": "JrUtil", "built": day.isoformat(), "nights": [d.isoformat() for d in days],
            "attribution": ATTRIBUTION, "license": LICENSE, "stops": rows}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.transit")
    parser.add_argument("out", help="stops file to write (JSON)")
    parser.add_argument("--feeds-dir", default="transit-feeds", help="folder for the downloaded GTFS files")
    parser.add_argument("--day", default=None, help="build day YYYY-MM-DD (default: today)")
    args = parser.parse_args(argv)
    feeds = []
    for name in FEEDS:
        path = Path(args.feeds_dir) / name
        download(JRUTIL_URL + name, path, timeout=600)
        feeds.append(path)
    day = date.fromisoformat(args.day) if args.day else date.today()
    res = build_stops(feeds, day)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"stops": len(res["stops"]), "nights": res["nights"], "bytes": out.stat().st_size}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())