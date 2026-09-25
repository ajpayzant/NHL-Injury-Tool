from datetime import date

from nhl_injuries import enrich
from nhl_injuries.nhl import PlayerMatcher, name_key, season_id, sync_players


def injury(iid="a", nhl_id="99", first="2026-10-10", ret="", team="COL", latest="", itype="Knee",
           player="Cale Makar", pid="1"):
    return {"injury_id": iid, "player_id": pid, "player": player, "position": "D", "team": team,
            "latest_team": latest or team, "injury_type": itype, "status": "Out", "first_seen": first,
            "last_seen": first, "return_date": ret, "nhl_id": nhl_id}


def schedule(team, dates):
    return {team: [(d, f"{team}{d}") for d in dates]}


GAMES = ["2026-10-09", "2026-10-11", "2026-10-13", "2026-10-15", "2026-10-17", "2026-10-19"]


def run(inj, dressed_dates, team="COL", events=()):
    tg = schedule(team, GAMES)
    dressed = {f"{team}{d}" for d in dressed_dates}
    return enrich.games_missed(inj, tg, enrich.team_spans(inj, list(events)), dressed, sorted(dressed_dates))


def test_games_missed_counts_until_he_plays_again():
    # Off the report on the 14th but doesn't dress until the 17th: the 15th counts too.
    r = run(injury(ret="2026-10-14"), ["2026-10-09", "2026-10-17", "2026-10-19"])
    assert r == {"games_missed": 3, "first_game_back": "2026-10-17", "return_check": "Played"}


def test_back_before_cbs_drops_him():
    r = run(injury(ret="2026-10-18"), ["2026-10-09", "2026-10-15", "2026-10-17"])
    assert r["games_missed"] == 2 and r["first_game_back"] == "2026-10-15"


def test_awaiting_and_not_played_since():
    assert run(injury(ret="2026-10-20"), [])["return_check"] == "Awaiting first game"
    r = run(injury(ret="2026-10-14"), [])
    assert r["return_check"] == "Not played since" and r["games_missed"] == 5


def test_open_injury_and_playing_while_listed():
    assert run(injury(), [])["return_check"] == "On report"
    r = run(injury(), ["2026-10-19"])
    assert r["return_check"] == "Playing while listed" and r["games_missed"] == 4


def test_unmatched_player():
    assert run(injury(nhl_id="", ret="2026-10-14"), [])["return_check"] == "No NHL match"


def test_traded_while_injured_counts_new_teams_games():
    inj = injury(ret="2026-10-18")
    events = [{"injury_id": "a", "event": "team_changed", "date": "2026-10-14", "detail": "COL -> BOS"}]
    tg = {**schedule("COL", ["2026-10-11", "2026-10-13", "2026-10-15"]),
          **schedule("BOS", ["2026-10-12", "2026-10-16", "2026-10-18"])}
    r = enrich.games_missed(inj, tg, enrich.team_spans(inj, events), {"BOS2026-10-18"}, ["2026-10-18"])
    # COL on the 11th and 13th, BOS on the 16th; COL's 15th and BOS's 12th don't count.
    assert r["games_missed"] == 3 and r["first_game_back"] == "2026-10-18"


def test_reinjury_flags():
    rows = [injury("a", first="2026-10-01", ret="2026-10-20", itype="Knee"),
            injury("b", first="2026-11-05", itype="Knee"),
            injury("c", first="2026-11-06", ret="2026-11-07", itype="Illness"),
            injury("d", nhl_id="7", player="Other Guy", pid="2", first="2026-10-25", itype="Ankle")]
    enrich.add_reinjuries(rows)
    assert (rows[1]["reinjury_match"], rows[1]["reinjury_of"], rows[1]["days_since_prior"]) == ("Same injury", "a", 16)
    assert rows[2]["reinjury_match"] == "" and rows[3]["reinjury_match"] == ""
    later = [injury("a", first="2026-10-01", ret="2026-10-20", itype="Knee"),
             injury("b", first="2026-10-30", itype="Ankle"),
             injury("e", first="2027-01-15", itype="Knee")]
    enrich.add_reinjuries(later)
    assert later[1]["reinjury_match"] == "Same body region"
    assert later[2]["reinjury_match"] == ""  # 87 days later


def test_expected_return_history():
    inj = injury(first="2026-09-25")
    events = [
        {"at": "2026-09-25T04:00Z", "date": "2026-09-25", "injury_id": "a", "event": "opened",
         "detail": "Knee - Expected to be out until at least Oct 2"},
        {"at": "2026-10-01T04:00Z", "date": "2026-10-01", "injury_id": "a", "event": "status_changed",
         "detail": "Expected to be out until at least Oct 2 -> Expected to be out until at least Oct 9"},
        {"at": "2026-10-05T04:00Z", "date": "2026-10-05", "injury_id": "a", "event": "status_changed",
         "detail": "Expected to be out until at least Oct 9 -> Expected to be out until at least Oct 7"},
    ]
    h = enrich.expected_return_history([inj], events)
    assert [r["change"] for r in h] == ["First report", "Pushed back 7 days", "Moved up 2 days"]
    assert h[-1]["expected_return"] == "2026-10-07" and all(r["date_known"] for r in h)
    # An imported injury with no events starts from its current status, date unknown.
    old = enrich.expected_return_history([injury(first="2026-05-07")], [])
    assert len(old) == 1 and not old[0]["date_known"]


def test_name_key_and_season_id():
    assert name_key("Tim Stützle") == "timstutzle" == name_key("Tim Stutzle")
    assert name_key("Ryan O'Reilly") == "ryanoreilly"
    assert season_id("2026-27") == "20262027"


class FakeClient:
    def __init__(self, rosters, search=()):
        self.rosters, self.search, self.calls = rosters, list(search), []

    def get(self, url, **params):
        self.calls.append(url)
        if "/roster/" in url:
            team = url.split("/roster/")[1].split("/")[0]
            return {"forwards": self.rosters.get(team, []), "defensemen": [], "goalies": []}
        if "search" in url:
            return self.search
        return {"birthDate": "1990-01-01", "position": "D", "currentTeamAbbrev": "CBJ"}


def p(pid, first, last, pos="C"):
    return {"id": pid, "firstName": {"default": first}, "lastName": {"default": last},
            "positionCode": pos, "birthDate": "2000-01-01"}


def test_matcher_roster_nickname_other_team_and_search():
    client = FakeClient({"COL": [p(1, "Alexander", "Kerfoot")], "BOS": [p(2, "Tim", "Stützle")]},
                        search=[{"playerId": 3, "name": "Brendan Smith", "positionCode": "D",
                                 "teamAbbrev": None, "lastTeamAbbrev": "CBJ"}])
    m = PlayerMatcher(client, ["20262027"])
    assert m.match("Alex Kerfoot", "COL", "C") == ({**m.roster("COL", "current")[0]}, "roster (nickname)")
    hit, how = m.match("Tim Stutzle", "OTT", "C")
    assert hit["nhl_id"] == "2" and how == "roster (other team)"
    hit, how = m.match("Brendan Smith", "CBJ", "D")
    assert hit["nhl_id"] == "3" and how == "search" and hit["birth_date"] == "1990-01-01"
    assert m.match("Nobody Here", "COL", "C") == (None, "unmatched")


def test_unmatched_players_are_retried_after_a_week():
    inj = [injury(nhl_id="", player="Nobody Here", pid="5")]
    client = FakeClient({})
    known = [{"key": "5", "player": "Nobody Here", "team": "COL", "nhl_id": "", "birth_date": "",
              "nhl_position": "", "matched_by": "unmatched", "checked": "2026-10-01"}]
    sync_players(client, inj, known, ["20262027"], date(2026, 10, 5))
    assert client.calls == []
    sync_players(client, inj, known, ["20262027"], date(2026, 10, 9))
    assert client.calls
