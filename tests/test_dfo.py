import json
from datetime import date

import pytest

from nhl_injuries import dfo


def item(i, created, name="Brock Faber", team="MIN", nhl_id=8482122, details="Faber (upper body) has been placed on IR.",
         updated=None, dfo_id=30792):
    return {"id": i, "createdAt": created, "updatedAt": updated or created, "playerName": name,
            "playerId": dfo_id, "playerFiveVFiveId": nhl_id, "playerPosition": "D", "teamAbbreviation": team,
            "details": details, "fantasyDetails": "", "sourceName": "Michael Russo",
            "sourceUrl": "https://x.com/RussoHockey/status/1", "breakingNews": False}


def page(items, last=2150):
    data = {"props": {"pageProps": {"data": {"data": items, "page": 1, "lastPage": last}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def test_parse_page_and_row():
    items, last = dfo.parse_page(page([item(1, "2026-09-29T02:30:00.000Z", details="Faber left Saturday�s game.  ")]))
    assert last == 2150
    row = dfo.to_row(items[0], "2026-09-29T03:00:00Z")
    assert row["date"] == "2026-09-28"          # 10:30 PM Eastern the night before
    assert row["published_at"] == "2026-09-29T02:30:00Z"
    assert row["headline"] == "Faber left Saturday's game."
    assert row["dfo_nhl_id"] == "8482122" and row["team"] == "MIN"


def test_parse_page_rejects_other_layouts():
    with pytest.raises(dfo.NewsError):
        dfo.parse_page("<html>nothing here</html>")


def test_free_agent_team_is_blank():
    assert dfo.to_row(item(1, "2026-04-23T12:00:00Z", team="FA"), "")["team"] == ""


def test_merge_keeps_first_team_and_counts_edits():
    stored, new, edited = dfo.merge([], [item(1, "2026-09-25T12:00:00Z", team="CBJ")], "2026-09-25T13:00:00Z")
    assert (new, edited) == (1, 0)
    # Traded: Daily Faceoff now shows TOR on the old item, and the text was edited.
    later = item(1, "2026-09-25T12:00:00Z", team="TOR", details="Faber (shoulder) is on IR.",
                 updated="2026-09-25T12:30:00Z")
    rows, new, edited = dfo.merge(stored, [later, item(2, "2026-09-29T12:00:00Z", team="TOR")], "2026-09-29T13:00:00Z")
    assert (new, edited) == (1, 1)
    old = next(r for r in rows if r["news_id"] == "1")
    assert old["team"] == "CBJ" and old["scraped_at"] == "2026-09-25T13:00:00Z"
    assert old["headline"] == "Faber (shoulder) is on IR."
    assert [r["news_id"] for r in rows] == ["2", "1"]   # newest first


class FakeClient:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def page(self, n):
        self.asked.append(n)
        return self.pages.get(n, []), len(self.pages)


def test_fetch_new_stops_once_past_the_overlap():
    pages = {1: [item(10, "2026-09-29T12:00:00Z")], 2: [item(9, "2026-09-27T12:00:00Z")],
             3: [item(8, "2026-09-20T12:00:00Z")], 4: [item(7, "2026-09-10T12:00:00Z")]}
    client = FakeClient(pages)
    got = dfo.fetch_new(client, [{"published_at": "2026-09-28T12:00:00Z"}])
    # Page 3 is the first to end before newest-stored minus 36h (Sep 27 00:00); page 4 isn't needed.
    assert client.asked == [1, 2, 3] and len(got) == 3
    client = FakeClient(pages)
    dfo.fetch_new(client, [], max_pages=3)       # empty store: bounded by max_pages
    assert client.asked == [1, 2, 3]


@pytest.mark.parametrize("headline,status", [
    ("Faber (upper body) has been placed on IR.", "IR"),
    ("Kuemper has been activated off of IR.", "Activated"),
    ("Nugent-Hopkins (lower-body) will not play Tuesday vs. the Canucks.", "Out"),
    ("Yurov (undisclosed) skated on Thursday but will not return vs. Calgary.", "Out"),
    ("Holmberg (upper-body) left Monday's game vs. Buffalo and did not return.", "Left game"),
    ("Stolarz (lower-body) will not return to Wednesday's game against the Capitals.", "Left game"),
    ("Couturier (undisclosed) will be a game-time decision vs. Columbus on Tuesday.", "Game-time decision"),
    ("Thompson is considered week-to-week with an undisclosed injury.", "Week-to-week"),
    ("Edmundson (undisclosed) is day-to-day.", "Day-to-day"),
    ("Kaprizov (lower-body) will return vs. Tampa Bay on Tuesday.", "Returning"),
    ("Ostlund (lower-body) is not expected to be available for the remainder of Buffalo's first round series.", "Out"),
    ("Luukkonen (lower-body) was a full participant in Tuesday's practice.", "Practicing"),
    ("Hughes has been shut down for the remainder of the 2025-26 season to undergo a procedure.", "Out for season"),
    ("Faber underwent surgery to repair a fractured skull and is out indefinitely.", "Out indefinitely"),
    ("Barzal was placed on the Injured Non-Roster list.", "Injured non-roster"),
    ("Klingberg has a lower-body injury and is being further evaluated.", "Being evaluated"),
])
def test_status(headline, status):
    assert dfo.parse_status(headline) == status


@pytest.mark.parametrize("headline,injury", [
    ("Faber (upper body) has been placed on IR.", "Upper Body"),
    ("Bernard-Docker is considered day-to-day with an upper-body injury.", "Upper Body"),
    ("Faber underwent surgery to repair a fractured skull and is out indefinitely.", "Head"),
    ("Lamoureux underwent successful shoulder surgery.", "Shoulder"),
    ("Sandin underwent surgery to repair a torn ACL in his right knee.", "Knee"),
    ("Daccord (undislcosed) missed practice on Friday.", "Undisclosed"),
    ("Marchenko (work visa) is questionable for Tuesday's game.", "Visa"),
    ("Strome is back in the Flames lineup on Saturday.", ""),
    ("Quillan has been recalled from the Marlies (AHL).", ""),
])
def test_injury(headline, injury):
    assert dfo.parse_injury(headline) == injury


@pytest.mark.parametrize("headline,text,earliest,latest", [
    ("Merzlikins (shoulder) is expected to be out for another 3-to-5 months.", "3-5 months", "2026-12-28", "2027-02-26"),
    ("Moore (lower body) will miss the next 2-4 weeks.", "2-4 weeks", "2026-10-13", "2026-10-27"),
    ("Fabbro (hand) is expected to miss at least one month.", "at least 1 month", "2026-10-29", ""),
    ("Mailloux (right hand) underwent surgery and will be re-evaluated in eight weeks.", "re-evaluated in 8 weeks",
     "2026-11-24", "2026-11-24"),
    ("Guhle is expected to return in four to five weeks.", "4-5 weeks", "2026-10-27", "2026-11-03"),
    ("Edmundson (undisclosed) is day-to-day.", "", "", ""),
    ("Gauthier played through two broken vertebrae in April.", "", "", ""),
    ("Nosek is out after getting hurt three weeks ago.", "", "", ""),
])
def test_timeline(headline, text, earliest, latest):
    assert dfo.parse_timeline(headline, date(2026, 9, 29)) == (text, earliest, latest)


def test_timeline_makes_other_status_out():
    assert dfo.parse("Robinson had knee surgery and will need 6-to-8 weeks of recovery.", "2026-07-24")["news_status"] == "Out"


def news_row(i, day, nhl_id="", dfo_nhl_id="", name="Elvis Merzlikins", dfo_id="5"):
    return {"news_id": str(i), "date": day, "player": name, "nhl_id": nhl_id, "dfo_nhl_id": dfo_nhl_id,
            "dfo_player_id": dfo_id, "team": "TOR", "position": "G", "headline": "x"}


def test_resolve_ids_fallbacks():
    news = [news_row(1, "2026-09-29"),                                        # name match
            news_row(2, "2026-09-29", dfo_nhl_id="8480893", name="Kirill Marchenko", dfo_id="7"),
            news_row(3, "2026-09-20", name="K. Marchenko", dfo_id="7"),         # same Daily Faceoff player
            news_row(4, "2026-09-29", name="John Gibson", dfo_id="9"),          # cached NHL.com match
            news_row(5, "2026-09-29", name="Nobody Known", dfo_id="11")]
    injuries = [{"player": "Elvis Merzlikins", "nhl_id": "8478007"}]
    players = [{"key": "dfo:9", "player": "John Gibson", "nhl_id": "8476434"}]
    dfo.resolve_ids(news, injuries, players)
    assert [(r["nhl_id"], r["matched_by"]) for r in news] == [
        ("8478007", "name"), ("8480893", "dfo"), ("8480893", "dfo (other item)"),
        ("8476434", "nhl.com"), ("", "unmatched")]


def test_link_injuries_window_and_nearest():
    injuries = [
        {"injury_id": "old", "nhl_id": "1", "first_seen": "2026-05-10", "return_date": "2026-05-20"},
        {"injury_id": "now", "nhl_id": "1", "first_seen": "2026-09-26", "return_date": ""},
    ]
    news = [news_row(1, "2026-09-22", nhl_id="1"),   # 4 days before CBS listed him
            news_row(2, "2026-09-29", nhl_id="1"),   # during the open injury
            news_row(3, "2026-05-22", nhl_id="1"),   # 2 days after the old one closed
            news_row(4, "2026-07-01", nhl_id="1"),   # between injuries
            news_row(5, "2026-09-29", nhl_id="2")]
    dfo.link_injuries(news, injuries, date(2026, 9, 29))
    assert [r["injury_id"] for r in news] == ["now", "now", "old", "", ""]
