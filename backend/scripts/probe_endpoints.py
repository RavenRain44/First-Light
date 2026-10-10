"""Phase 1 probe: hit every upstream endpoint once and save the real response.

Parsers in adapters/ are written against these files, not against guessed shapes.
Run from backend/:  python -m scripts.probe_endpoints

Writes backend/fixtures/probe/*.json and backend/fixtures/probe/SHAPES.md.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "probe"
LAT, LON = 42.0308, -93.6319
UA = os.environ.get("NWS_USER_AGENT", "ClosureCall-HackMidwest2026 (contact: set NWS_USER_AGENT)")
IEM = "https://mesonet.agron.iastate.edu/api/1"

# (filename, url). Historical samples use the 2023-02-22 ice storm and 2020-08-10 derecho.
PROBES = [
    ("nws_points.json", f"https://api.weather.gov/points/{LAT},{LON}"),
    ("nws_alerts_point.json", f"https://api.weather.gov/alerts/active?point={LAT},{LON}"),
    ("nws_alerts_zone.json", "https://api.weather.gov/alerts/active?zone=IAZ048"),
    ("nws_alerts_national.json", "https://api.weather.gov/alerts/active"),
    ("nws_gridpoints.json", "https://api.weather.gov/gridpoints/DMX/73,69"),
    ("nws_stations.json", "https://api.weather.gov/gridpoints/DMX/73,69/stations"),
    ("nws_zone_IAZ048.json", "https://api.weather.gov/zones/forecast/IAZ048"),
    ("iem_currents_AMW.json", f"{IEM}/currents.json?station=AMW"),
    ("iem_obhistory_AMW.json", f"{IEM}/obhistory.json?network=IA_ASOS&station=AMW&date=2023-02-22&full=true"),
    ("iem_roadcond_2023-02-22T20.geojson", f"{IEM}/iowa_winter_roadcond.geojson?valid=2023-02-22T20:00:00Z"),
    ("iem_rwis_2024-01-12T18.json", f"{IEM}/rwis.json?valid=2024-01-12T18:00:00Z"),
    ("iem_vtec_status_2023-02-22T14.json", f"{IEM}/vtec/events_status.json?valid=2023-02-22T14:00:00Z&wfo=DMX"),
    ("iem_county_zone_2023-02-22T14.json", f"{IEM}/vtec/county_zone.json?valid=2023-02-22T14:00:00Z"),
    ("iem_lsr_derecho.json", f"{IEM}/nws/lsrs_by_point.json?lat={LAT}&lon={LON}&radius_miles=25&begints=2020-08-10T12:00:00Z&endts=2020-08-11T06:00:00Z"),
    ("iem_mos_nbs_2023-02-22T01.json", f"{IEM}/mos.json?station=KAMW&model=NBS&runtime=2023-02-22T01:00:00Z"),
    ("iem_outlook_2020-08-10T12.json", f"{IEM}/nws/outlook_by_point.json?lat={LAT}&lon={LON}&valid=2020-08-10T12:00:00Z"),
    ("iem_vtec_byugc_IAZ048.json", "https://mesonet.agron.iastate.edu/json/vtec_events_byugc.php?ugc=IAZ048&sdate=2019-01-01&edate=2026-10-01"),
]

# Big national/statewide payloads are trimmed before saving so the repo stays small.
TRIM = {"nws_alerts_national.json": 60, "iem_rwis_2024-01-12T18.json": 0,
        "iem_roadcond_2023-02-22T20.geojson": 0, "iem_county_zone_2023-02-22T14.json": 0}


def _near(feature, deg=0.6) -> bool:
    coords = feature["geometry"]["coordinates"]
    while isinstance(coords[0], list):
        coords = coords[0]
    return abs(coords[1] - LAT) < deg and abs(coords[0] - LON) < deg


def describe(obj, depth=0, max_depth=3) -> list[str]:
    pad = "  " * depth
    lines: list[str] = []
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:60]:
            t = type(v).__name__
            sample = "" if isinstance(v, (dict, list)) else f" = {str(v)[:60]!r}"
            lines.append(f"{pad}- `{k}`: {t}{sample}")
            if isinstance(v, (dict, list)) and depth < max_depth:
                lines += describe(v, depth + 1, max_depth)
    elif isinstance(obj, list) and obj:
        lines.append(f"{pad}- [list of {len(obj)}] first item:")
        lines += describe(obj[0], depth + 1, max_depth)
    return lines


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    md = ["# Probed response shapes", "", f"Generated {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} by scripts/probe_endpoints.py", ""]
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/geo+json, application/json"}, timeout=60) as c:
        for name, url in PROBES:
            try:
                r = c.get(url)
                data = r.json()
            except Exception as e:  # noqa: BLE001
                md += [f"## {name}", f"`{url}`", f"FAILED: {e}", ""]
                continue
            if name in TRIM:
                if "roadcond" in name:
                    data["features"] = [f for f in data["features"] if _near(f)]
                elif "features" in data:
                    data["features"] = data["features"][: TRIM[name]]
                elif "county_zone" in name:
                    data["data"] = [d for d in data["data"] if d.get("ugc", "").startswith("IA")]
                elif "data" in data:
                    data["data"] = [d for d in data["data"] if d.get("network") == "IA_RWIS"]
            (OUT / name).write_text(json.dumps(data))
            md += [f"## {name}", f"`{url}` → HTTP {r.status_code}", ""] + describe(data) + [""]
            time.sleep(0.3)  # IEM asks clients to be gentle
    (OUT / "SHAPES.md").write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {len(PROBES)} probes to {OUT}")


if __name__ == "__main__":
    main()
