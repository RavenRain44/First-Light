"""AI explanation backtest: result categories and rates."""
from scripts.backtest_ai import kind, summarise


def row(result, status="NORMAL", problems=()):
    return {"day": "2024-01-09", "status_computed": status, "result": result, "provider": "akamai", "model_id": "m",
            "attempts": 1, "problems": list(problems), "tokens": 100, "seconds": 1.0, "headline": "h"}


def test_summary_rates_and_problem_categories():
    s = summarise([row("accepted_first_try"), row("accepted_after_repair", "CLOSED", ["numbers not found in snapshot: 7"]),
                   row("template_fallback", "CLOSED", ["summary does not name the recommended posture CLOSED", "brief recommends NORMAL, not CLOSED"])])
    assert s["n_days"] == 3 and abs(s["accepted_rate"] - 2 / 3) < 1e-9 and abs(s["first_try_rate"] - 1 / 3) < 1e-9
    assert s["by_computed_status"]["CLOSED"] == {"n": 2, "accepted_after_repair": 1, "template_fallback": 1}
    assert s["rejected_attempts_by_problem"] == {"number not in the data": 1, "did not name the computed status": 1,
                                                 "recommended a different status": 1}
    assert s["status"] == "not enough data" and "not a weather-accuracy score" in s["what_this_measures"]


def test_empty_and_unknown():
    assert summarise([])["accepted_rate"] is None
    assert kind("something new") == "other" and kind("model call failed: ConnectError") == "call failed (network/auth/timeout)"
