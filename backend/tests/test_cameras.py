"""Iowa DOT camera layer: parsing real IEM data, nearest selection, no hindsight, safe image proxy."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from adapters import iem_cameras
from adapters.iem_cameras import IMAGE_URL, image_time, parse_cameras, split_names
from app.facility import load_facility

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "probe" / "iem_rwiscam_2023-02-22T12.geojson"
GJ = json.loads(FIX.read_text(encoding="utf-8"))
FAC = load_facility()
T = datetime(2023, 2, 22, 12, 30, tzinfo=timezone.utc)


def test_parses_real_response_nearest_first():
    cams = parse_cameras(GJ, FAC, T, live=False, nearest=20)
    assert len(cams) == 20
    assert [c["km"] for c in cams] == sorted(c["km"] for c in cams)
    c = cams[0]
    assert c["views"] and all(v["url"].endswith(".jpg") for v in c["views"])
    assert c["direction"] in {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}


def test_never_shows_images_taken_after_as_of():
    early = datetime(2023, 2, 22, 11, 0, tzinfo=timezone.utc)  # every frame in the fixture is ~11:58-12:05
    assert parse_cameras(GJ, FAC, early, live=False) == []
    for c in parse_cameras(GJ, FAC, T, live=False):
        assert all(datetime.fromisoformat(v["time"]) <= T for v in c["views"])


def test_live_drops_stale_feeds():
    much_later = datetime(2023, 2, 22, 20, 0, tzinfo=timezone.utc)
    assert parse_cameras(GJ, FAC, much_later, live=True) == []      # 8 h old: treated as offline
    assert parse_cameras(GJ, FAC, much_later, live=False) != []     # replay still shows the archive frame


def test_image_url_whitelist():
    ok = "https://mesonet.agron.iastate.edu/archive/data/2023/02/22/camera/IDOT-008-00/IDOT-008-00_202302221158.jpg"
    assert IMAGE_URL.match(ok) and image_time(ok) == datetime(2023, 2, 22, 11, 58, tzinfo=timezone.utc)
    for bad in ("https://example.com/x.jpg", "http://mesonet.agron.iastate.edu/archive/data/2023/02/22/camera/a/a_202302221158.jpg",
                "https://mesonet.agron.iastate.edu/archive/data/../../etc/passwd", "file:///c:/x.jpg"):
        assert not IMAGE_URL.match(bad)


def test_image_proxy_refuses_other_hosts():
    import asyncio
    with pytest.raises(ValueError):
        asyncio.run(iem_cameras.get_image("https://example.com/x.jpg"))


def test_demo_mode_serves_only_cached_images(tmp_path, monkeypatch):
    import asyncio
    monkeypatch.setattr(iem_cameras, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(iem_cameras.settings, "demo_mode", True)
    url = "https://mesonet.agron.iastate.edu/archive/data/2023/02/22/camera/IDOT-008-00/IDOT-008-00_202302221158.jpg"
    assert asyncio.run(iem_cameras.get_image(url)) is None  # not cached: no network in demo mode
    iem_cameras.image_path(url).write_bytes(b"\xff\xd8jpeg")
    assert asyncio.run(iem_cameras.get_image(url)) == b"\xff\xd8jpeg"


def test_view_labels():
    site, labels = split_names({0: "Adair I80 North", 2: "Adair I80 Bridge Deck"})
    assert site == "Adair I80" and labels == {0: "North", 2: "Bridge Deck"}
    site, labels = split_names({0: "De Soto (I-80/US 169)", 1: "De Soto (I-80/US 169)"})
    assert labels == {0: "View 1", 1: "View 2"}
