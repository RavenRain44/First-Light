"""One-off: gzip legacy .json cache entries, simplify cached road geometry, drop unused endpoints."""
import gzip
import json
from pathlib import Path

from adapters.iem_roads import simplify

CACHE = Path(__file__).resolve().parents[1] / "fixtures" / "http_cache"
for f in CACHE.glob("*.json"):
    d = json.loads(f.read_text(encoding="utf-8"))
    if "county_zone.json" in d["url"]:
        f.unlink()
        continue
    if "iowa_winter_roadcond" in d["url"] and "data" in d:
        for feat in d["data"].get("features", []):
            feat["geometry"] = simplify(feat["geometry"])
    with gzip.open(f.with_suffix(".json.gz"), "wt", encoding="utf-8") as fh:
        json.dump(d, fh, separators=(",", ":"))
    f.unlink()
print(sum(p.stat().st_size for p in CACHE.glob("*.gz")) / 1e6, "MB in", len(list(CACHE.glob("*.gz"))), "files")
