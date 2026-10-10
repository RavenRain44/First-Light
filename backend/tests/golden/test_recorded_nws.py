import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "nws"


def test_three_recorded_alerts_are_real_and_traceable():
    paths = sorted(FIXTURES.glob("real-alert-*.json"))
    assert len(paths) == 3
    for path in paths:
        data = json.loads(path.read_text())
        assert data["replay_only"] is True
        assert data["source_url"].startswith("https://api.weather.gov/")
        properties = data["feature"]["properties"]
        assert properties["event"]
        assert properties["sent"]


def test_recorded_gridpoint_has_fields_the_parser_uses():
    data = json.loads((FIXTURES / "real-gridpoint-dmx.json").read_text())
    properties = data["payload"]["properties"]
    assert "windGust" in properties
    assert "temperature" in properties
    assert data["replay_only"] is True
