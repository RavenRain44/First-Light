"""Iowa DOT camera layer: parsing real IEM data, nearest selection, no hindsight, safe image proxy."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from adapters import iem_cameras
from adapters.iem_cameras import IMAGE_URL, image_time, parse_cameras, parse_webcams, split_names
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


# ----------------------------------------------------------------------------- Iowa DOT traffic cameras

TRAFFIC = json.loads((FIX.parent / "iowadot_traffic_cameras_ames.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 10, 23, 0, tzinfo=timezone.utc)


def test_traffic_cameras_nearest_with_live_video():
    from adapters.iowadot_cameras import VIDEO_URL, parse_traffic_cameras
    cams = parse_traffic_cameras(TRAFFIC, FAC, NOW, nearest=50)
    assert cams and [c["km"] for c in cams] == sorted(c["km"] for c in cams)
    assert cams[0]["km"] < 5  # US 30 cameras are minutes from the facility; RWIS sites are ~50 km out
    for c in cams:
        assert c["kind"] == "traffic" and VIDEO_URL.match(c["stream_url"])
        assert c["views"][0]["url"] == c["snapshot_url"]
        assert not c["name"].startswith(("AM - ", "WWD - "))
    assert not any("Parking Only" in c["name"] for c in cams)  # rest-area cameras have no video


def test_traffic_cameras_spread_around_the_facility():
    from adapters.iowadot_cameras import NEAREST, SPREAD_KM, parse_traffic_cameras
    everything = parse_traffic_cameras(TRAFFIC, FAC, NOW, nearest=500)
    cams = parse_traffic_cameras(TRAFFIC, FAC, NOW)
    assert len(cams) == NEAREST
    # every direction with a camera is represented, not just the US 30 / I-35 interchange
    assert {c["direction"] for c in cams} == {c["direction"] for c in everything}
    assert any(c["id"].startswith("BN") for c in cams)  # Boone, west
    assert any(c["id"].startswith("NV") for c in cams)  # Nevada, east
    assert any(c["direction"] == "N" for c in cams)     # I-35 north (Ellsworth)
    # beyond each direction's nearest camera, nothing far away
    by_dir = {}
    for c in cams:
        by_dir.setdefault(c["direction"], []).append(c["km"])
    assert all(km <= SPREAD_KM for kms in by_dir.values() for km in sorted(kms)[1:])


def test_traffic_cameras_one_per_pole():
    from adapters.iem_cameras import _km
    from adapters.iowadot_cameras import parse_traffic_cameras
    cams = parse_traffic_cameras(TRAFFIC, FAC, NOW, nearest=50)
    ids = {c["id"] for c in cams}
    assert "AMTV16" in ids and "WWDTV01" not in ids  # same spot: the general camera wins over wrong-way detection
    assert "AMTV06" in ids and "AMTV06Q" not in ids
    for i, a in enumerate(cams):
        assert all(_km(a["lat"], a["lon"], b["lat"], b["lon"]) >= 0.15 for b in cams[i + 1:])


def test_traffic_url_allowlists():
    from adapters.iowadot_cameras import SNAPSHOT_URL, VIDEO_URL
    assert VIDEO_URL.match("https://video4.iowadot.gov:8888/ames/amtv16lb/playlist.m3u8")
    assert VIDEO_URL.match("https://video.iowadot.gov/ames/amtv16lb/playlist.m3u8")  # announced host move
    assert SNAPSHOT_URL.match("https://atmsqf.iowadot.gov/SNAPSHOTS/PUBLIC/Metro/amtv16hd.jpeg")
    for bad in ("https://video4.iowadot.gov.evil.com/x.m3u8", "http://video4.iowadot.gov/x.m3u8",
                "https://atmsqf.iowadot.gov/SNAPSHOTS/PUBLIC/../../x.jpeg", "https://atmsqf.iowadot.gov/other/x.jpeg"):
        assert not (VIDEO_URL.match(bad) or SNAPSHOT_URL.match(bad))


def test_merge_live_keeps_a_few_rwis_sites():
    from adapters.iowadot_cameras import RWIS_NEAREST, merge_live, parse_traffic_cameras
    rwis = parse_cameras(GJ, FAC, T, live=False, nearest=20)
    traffic = parse_traffic_cameras(TRAFFIC, FAC, NOW)
    webcams = parse_webcams(WEBCAM_FIX["ISUC"], FAC, T, live=False)
    merged = merge_live(rwis, traffic, webcams)
    assert sum(c["kind"] == "rwis" for c in merged) == RWIS_NEAREST
    assert sum(c["kind"] == "webcam" for c in merged) == len(webcams)
    assert [c["km"] for c in merged] == sorted(c["km"] for c in merged)
    assert merge_live(rwis, []) == rwis  # replay: all RWIS cameras


def test_snapshot_fetched_fresh_online_cached_in_demo(tmp_path, monkeypatch):
    import asyncio
    url = "https://atmsqf.iowadot.gov/SNAPSHOTS/PUBLIC/Metro/amtv16hd.jpeg"
    monkeypatch.setattr(iem_cameras, "IMAGE_DIR", tmp_path)
    iem_cameras.image_path(url).write_bytes(b"old")
    calls = []

    async def fake_download(u, path):
        calls.append(u)
        return b"new"
    monkeypatch.setattr(iem_cameras, "_download", fake_download)
    monkeypatch.setattr(iem_cameras.settings, "demo_mode", False)
    assert asyncio.run(iem_cameras.get_image(url)) == b"new" and calls == [url]  # never served stale online
    monkeypatch.setattr(iem_cameras.settings, "demo_mode", True)
    assert asyncio.run(iem_cameras.get_image(url)) == b"old" and calls == [url]  # demo: cached still, no network


# ----------------------------------------------------------------------------- ISU / KCCI webcams

WEBCAM_FIX = {n: json.loads((FIX.parent / f"iem_webcams_{n}_2023-02-22T12.json").read_text(encoding="utf-8"))
              for n in ("ISUC", "KCCI")}


def test_webcams_group_views_by_site():
    cams = {c["name"]: c for c in parse_webcams(WEBCAM_FIX["ISUC"], FAC, T, live=False)}
    assert set(cams) == {"ISU Curtis Hall", "ISU Design", "ISU Memorial Union"}
    curtis = cams["ISU Curtis Hall"]
    assert curtis["id"] == "ISUC-004" and curtis["kind"] == "webcam" and curtis["km"] < 2
    assert [v["label"] for v in curtis["views"]] == ["Left · facing SW", "Center · facing W", "Right · facing NW"]
    assert all(IMAGE_URL.match(v["url"]) for v in curtis["views"])  # served by the existing image proxy
    farm = parse_webcams(WEBCAM_FIX["KCCI"], FAC, T, live=False)
    assert [c["name"] for c in farm] == ["ISU Ag Farm"]  # the other KCCI cameras are too far away


def test_webcams_no_hindsight_and_stale_feeds():
    early = datetime(2023, 2, 22, 11, 0, tzinfo=timezone.utc)  # every frame in the fixture is 12:00
    assert parse_webcams(WEBCAM_FIX["ISUC"], FAC, early, live=False) == []
    later = datetime(2023, 2, 22, 20, 0, tzinfo=timezone.utc)
    assert parse_webcams(WEBCAM_FIX["ISUC"], FAC, later, live=True) == []   # 8 h old: offline
    assert parse_webcams(WEBCAM_FIX["ISUC"], FAC, later, live=False) != []  # replay keeps the archive frame


def test_webcam_urls_live_vs_replay():
    from adapters.iem_cameras import webcams_urls
    assert webcams_urls(T, live=True) == ["https://mesonet.agron.iastate.edu/json/webcams.php?network=ISUC",
                                          "https://mesonet.agron.iastate.edu/json/webcams.php?network=KCCI"]
    assert all(u.endswith("&ts=2023-02-22T12:00:00Z") for u in webcams_urls(T, live=False))  # 3-hour archive grid
