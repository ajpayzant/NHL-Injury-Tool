from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from nhl_injuries.reference import expected_return, season_of, status_category
from nhl_injuries.scrape import ReportRow, ScrapeError, parse_report, parse_updated
from nhl_injuries.tracker import MISSES_TO_CLOSE, apply_report

FIXTURE = Path(__file__).parent / "fixtures" / "cbs_2026-09-24.html"
T0 = datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc)  # noon Eastern


def row(pid="1", player="Cale Makar", pos="D", team="COL", itype="Lower Body",
        status="Day-to-Day"):
    return ReportRow(pid, player, pos, team, itype, status, "")


def filler(n=25):
    """Unrelated players so the row-count guard has a realistic report to compare."""
    return [row(pid=f"f{i}", player=f"Filler Player{i}", team="BOS") for i in range(n)]


class Sim:
    """Feed reports through the tracker the way the scheduled job does, 12h apart."""

    def __init__(self):
        self.injuries, self.runs, self.events, self.n = [], [], [], 0

    def run(self, report, force=False):
        now = T0 + timedelta(hours=12 * self.n)
        self.n += 1
        res = apply_report(self.injuries, self.runs, report, now, force=force)
        self.injuries, self.events = res.injuries, self.events + res.events
        self.runs.append(res.run)
        return res

    def ep(self, player="Cale Makar"):
        return [i for i in self.injuries if i["player"] == player]


def test_new_injury_opens_once_and_updates():
    s = Sim()
    s.run([row()] + filler())
    s.run([row(status="Expected to be out until at least Oct 10")] + filler())
    (ep,) = s.ep()
    assert ep["first_seen"] == "2026-10-01" and ep["last_seen"] == "2026-10-02"
    assert ep["return_date"] == "" and ep["status_category"] == "Out"
    assert ep["expected_return"] == "2026-10-10" and ep["season"] == "2026-27"


def test_one_missed_scrape_does_not_close():
    s = Sim()
    s.run([row()] + filler())
    s.run(filler())
    assert s.ep()[0]["return_date"] == ""


def test_closes_after_consecutive_misses_dated_to_first_miss():
    s = Sim()
    s.run([row()] + filler())      # 10-01 12:00 ET
    s.run([row()] + filler())      # 10-02 00:00 ET
    s.run(filler())                # 10-02 12:00 ET  <- first miss
    s.run(filler())                # 10-03 00:00 ET
    assert MISSES_TO_CLOSE == 2
    (ep,) = s.ep()
    assert ep["return_date"] == "2026-10-02"
    assert ep["days_out"] == 1
    assert [e["event"] for e in s.events if e["player"] == "Cale Makar"] == ["opened", "closed"]


def test_trade_while_injured_keeps_one_episode():
    s = Sim()
    s.run([row(team="STL", player="Jordan Kyrou", pid="9")] + filler())
    s.run([row(team="WSH", player="Jordan Kyrou", pid="9")] + filler())
    (ep,) = s.ep("Jordan Kyrou")
    assert ep["team"] == "STL" and ep["latest_team"] == "WSH"
    assert any(e["event"] == "team_changed" for e in s.events)


def test_type_refinement_updates_same_episode():
    s = Sim()
    s.run([row(itype="Upper Body")] + filler())
    s.run([row(itype="Shoulder")] + filler())
    (ep,) = s.ep()
    assert ep["injury_type"] == "Shoulder" and ep["category"] == "Upper Body"


def test_flicker_reopens_instead_of_duplicating():
    s = Sim()
    s.run([row()] + filler())
    s.run(filler())
    s.run(filler())                # closed
    assert s.ep()[0]["return_date"]
    s.run([row()] + filler())      # back within REOPEN_DAYS, same injury
    (ep,) = s.ep()
    assert ep["return_date"] == "" and ep["first_seen"] == "2026-10-01"


def test_new_injury_after_return_is_a_new_episode():
    s = Sim()
    s.run([row(itype="Knee")] + filler())
    s.run(filler())
    s.run(filler())                # closed 10-01 -> 10-02
    s.run([row(itype="Concussion")] + filler())  # different body region
    eps = s.ep()
    assert len(eps) == 2 and sorted(e["injury_type"] for e in eps) == ["Concussion", "Knee"]


def test_reappearing_long_after_return_is_a_new_episode():
    s = Sim()
    s.run([row()] + filler())
    for _ in range(10):
        s.run(filler())
    s.run([row()] + filler())
    assert len(s.ep()) == 2


def test_legacy_row_without_id_is_matched_by_name_and_gets_id():
    s = Sim()
    s.injuries = [{
        "injury_id": "legacy1", "player_id": "", "player": "Cale Makar", "position": "D",
        "team": "COL", "latest_team": "COL", "injury_type": "Lower Body", "status": "Day-to-Day",
        "first_seen": "2026-09-16", "last_seen": "2026-09-30", "last_seen_at": "2026-09-30T16:00:00Z",
        "source_updated": "", "return_date": "", "start_is_lower_bound": False,
        "return_is_estimated": False, "origin": "sheet", "notes": "",
    }]
    s.run([row(pid="555")] + filler())
    (ep,) = s.ep()
    assert ep["injury_id"] == "legacy1" and ep["player_id"] == "555"
    assert ep["first_seen"] == "2026-09-16"


def test_empty_scrape_raises_and_changes_nothing():
    s = Sim()
    s.run([row()] + filler())
    with pytest.raises(ScrapeError):
        s.run([])
    assert s.ep()[0]["return_date"] == ""


def test_sharp_drop_is_refused_unless_forced():
    s = Sim()
    s.run([row()] + filler(40))
    with pytest.raises(ScrapeError):
        s.run(filler(10))
    s.run(filler(10), force=True)  # a real drop can still be pushed through


def test_parse_fixture_page():
    rows = parse_report(FIXTURE.read_text(encoding="utf-8"), date(2026, 9, 24))
    assert len(rows) == 67
    assert all(r.player_id.isdigit() for r in rows)
    assert {r.team for r in rows} >= {"CBJ", "LAK", "MTL", "NJD", "SJS", "TBL", "VGK", "WSH"}
    helleson = next(r for r in rows if r.player == "Drew Helleson")
    assert (helleson.team, helleson.position, helleson.source_updated) == ("ANA", "D", "2026-09-22")


def test_date_helpers():
    assert season_of("2026-05-07") == "2025-26"
    assert season_of("2026-07-01") == "2026-27"
    assert parse_updated("Tue, Dec 30", date(2027, 1, 2)) == "2026-12-30"
    assert parse_updated("Thu, Sep 24", date(2026, 9, 24)) == "2026-09-24"
    assert expected_return("Expected to be out until at least Jan 5", date(2026, 12, 20)) == date(2027, 1, 5)
    assert status_category("IR. Out for the season") == "Out for season"
    assert status_category("IR. Expected to be out until at least Jul 1") == "Out for season"
    assert status_category("Questionable for start of season") == "Questionable"
