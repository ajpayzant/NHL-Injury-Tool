"""The News page's source comparisons: Daily Faceoff status changes, NHL.com report
diffs and the CBS / Daily Faceoff / NHL.com cross-check."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import core  # noqa: E402
from nhl_injuries import dfo  # noqa: E402

ET = "America/New_York"


def item(pkey, status, when, source="Daily Faceoff", url="", headline="h", team="MTL"):
    t = pd.Timestamp(when, tz=ET)
    return {"news_id": f"{pkey}:{when}:{source}", "pkey": pkey, "player": pkey.title(), "position": "C",
            "team_shown": team, "news_status": status, "tone": dfo.TONE.get(status, ""), "headline": headline,
            "published_at": t, "date": t.normalize().tz_localize(None), "source": source, "source_url": url,
            "updated_at": t.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")}


def test_status_changes_compares_before_the_window_with_the_latest():
    n = pd.DataFrame([item("a", "Out", "2026-11-10 12:00"), item("a", "Game-time decision", "2026-11-18 12:00"),
                      item("a", "Returning", "2026-11-19 12:00"),
                      item("b", "Day-to-day", "2026-11-18 10:00"), item("b", "IR", "2026-11-19 10:00"),
                      item("c", "Out", "2026-11-18 10:00"),  # one item: nothing to compare
                      item("d", "Activated", "2026-11-18 10:00"), item("d", "Returning", "2026-11-19 10:00"),
                      item("e", "Out", "2026-11-18 10:00"), item("e", "Other", "2026-11-19 10:00")])
    got = core.status_changes(n, pd.Timestamp("2026-11-18")).set_index("pkey")
    assert set(got.index) == {"a", "b"}
    assert got.loc["a", ["was_status", "news_status", "direction", "updates"]].tolist() == ["Out", "Returning", "Better", 2]
    assert got.loc["b", ["was_status", "news_status", "direction"]].tolist() == ["Day-to-day", "IR", "Worse"]


def test_report_diff_new_changed_carried_dropped():
    u1, u2 = "https://nhl.com/r1", "https://nhl.com/r2"
    n = pd.DataFrame([item("a", "Out", "2026-11-18 13:00", "NHL.com", u1), item("b", "Day-to-day", "2026-11-18 13:00", "NHL.com", u1),
                      item("c", "Out", "2026-11-18 13:00", "NHL.com", u1),
                      item("a", "Out", "2026-11-19 13:00", "NHL.com", u2), item("b", "IR", "2026-11-19 13:00", "NHL.com", u2),
                      item("d", "Returning", "2026-11-19 13:00", "NHL.com", u2)])
    d = core.report_diff(n, u2)
    assert d["prev"] == u1
    assert list(d["new"]["pkey"]) == ["d"] and list(d["carried"]["pkey"]) == ["a"]
    assert d["changed"][["pkey", "was_status", "news_status"]].values.tolist() == [["b", "Day-to-day", "IR"]]
    assert list(d["dropped"]["pkey"]) == ["c"]
    first = core.report_diff(n, u1)
    assert first["prev"] == "" and first["new"].empty


def test_cross_check_issues():
    n = pd.DataFrame([item("back", "Returning", "2026-11-19 10:00"),
                      item("lighter", "Game-time decision", "2026-11-19 10:00"),
                      item("worse", "Week-to-week", "2026-11-19 10:00"),
                      item("gone", "Out", "2026-11-19 10:00"),
                      item("split", "Returning", "2026-11-19 09:00"),
                      item("split", "Out", "2026-11-19 14:00", "NHL.com", "u"),
                      item("fine", "Out", "2026-11-19 10:00")])
    inj = pd.DataFrame([{"pkey": k, "is_open": True, "first_seen": pd.Timestamp("2026-11-01"), "status": s,
                         "status_category": cat, "on_ir": ir}
                        for k, s, cat, ir in [("back", "Out", "Out", False), ("lighter", "IR", "Out", True),
                                              ("worse", "Day-to-day", "Day-to-day", False),
                                              ("split", "Out", "Out", False), ("fine", "Out", "Out", False)]])
    got = dict(core.cross_check(inj, n, pd.Timestamp("2026-11-18"))[["pkey", "issue"]].values.tolist())
    assert got == {"back": "News says back, CBS still lists him", "lighter": "CBS more serious than news",
                   "worse": "News more serious than CBS", "gone": "Not on CBS report",
                   "split": "Daily Faceoff and NHL.com differ"}
