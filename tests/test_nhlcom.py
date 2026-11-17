import json
from datetime import date
from pathlib import Path

import pytest

from nhl_injuries import dfo, nhlcom

FIXTURE = Path(__file__).parent / "fixtures" / "nhlcom_status_2026-11-17.json"
STAMP = "2026-11-17T22:00:00Z"


def ent(name, pid):
    slug = name.lower().replace(" ", "-")
    return f'<forge-entity title="{name}" slug="{slug}-{pid}" code="player">{name}</forge-entity>'


def story(sections, slug="nhl-status-report-news-and-notes-november-20-2026",
          published="2026-11-20T20:40:00Z", updated="2026-11-20T21:00:00.123Z"):
    """A Status Report with one markdown part per (team name, body)."""
    parts = [{"type": "markdown", "content": "*Welcome to the NHL Status Report.*"}]
    parts += [{"type": "markdown", "content": f"## **{team}**\n\n{body}"} for team, body in sections]
    return {"slug": slug, "contentDate": published, "lastUpdatedDate": updated, "parts": parts}


def tagged(rows):
    """{player: (status, injury, timeline)} after the full refresh."""
    dfo.refresh(rows, [], [], date(2026, 11, 20))
    return {r["player"]: (r["news_status"], r["injury"], r["timeline"]) for r in rows}


@pytest.fixture(scope="module")
def nov17():
    rows = nhlcom.parse_story(json.loads(FIXTURE.read_text(encoding="utf-8")), STAMP)
    dfo.refresh(rows, [], [], date(2026, 11, 17))
    return {r["player"]: r for r in rows}


def test_real_report_rows(nov17):
    assert len(nov17) == 22
    h = nov17["Miro Heiskanen"]
    assert h["team"] == "DAL" and h["nhl_id"] == "8480036" and h["matched_by"] == "nhl.com tag"
    assert h["news_id"] == "nhlcom:nhl-status-report-news-and-notes-november-17-2026:8480036"
    assert h["published_at"] == "2026-11-17T20:42:00Z" and h["updated_at"] == "2026-11-17T21:13:08Z"
    assert h["date"] == "2026-11-17" and h["source_name"] == "NHL.com Status Report"
    assert h["source_url"] == "https://www.nhl.com/news/nhl-status-report-news-and-notes-november-17-2026"
    # Game time and TV channels are dropped from the headline.
    assert h["headline"] == ("Miro Heiskanen will return for the Stars to play the Vegas Golden Knights on "
                             "Tuesday, the first of consecutive road games at T-Mobile Arena.")
    assert "hit into the boards by Justin Sourdif" in h["context"]
    for r in nov17.values():
        assert "<" not in r["headline"] + r["context"] and "*" not in r["headline"]


def test_real_report_subjects(nov17):
    # Named in passing: not a subject of its own.
    assert "Justin Sourdif" not in nov17 and "Troy Stecher" not in nov17
    # Both co-subjects, and the mid-paragraph "Forward Brett Leason was recalled".
    assert {"Aleksander Barkov", "Brad Marchand", "Philip Broberg", "Jake Neighbours", "Brett Leason"} <= set(nov17)
    assert nov17["Brett Leason"]["headline"] == "Forward Brett Leason was recalled from San Jose of the AHL."
    assert nov17["Kiefer Sherwood"]["context"].endswith("in 23 games.")


@pytest.mark.parametrize("player, status, injury", [
    ("Miro Heiskanen", "Returning", "Upper Body"),       # injury from the background
    ("Lian Bichsel", "Out", "Lower Body"),
    ("Morgan Rielly", "Game-time decision", "Lower Body"),  # "could return"
    ("Olli Maatta", "Out", "Upper Body"),                 # not "Left game" from "8:05 left in the third"
    ("Philip Broberg", "Game-time decision", "Lower Body"),  # his own parenthetical, not Neighbours'
    ("Jake Neighbours", "Game-time decision", "Upper Body"),
    ("Logan Stanley", "Out", "Undisclosed"),
    ("Jonathan Huberdeau", "Practicing", ""),             # conditioning loan
    ("Tyler Boucher", "Other", ""),                       # NHL debut is not an injury return
    ("Pavel Dorofeyev", "Out", "Lower Body"),             # "missed the Rangers' win"
    ("Kiefer Sherwood", "Week-to-week", "Upper Body"),
])
def test_real_report_tags(nov17, player, status, injury):
    assert (nov17[player]["news_status"], nov17[player]["injury"]) == (status, injury)


def test_timeline_and_daily_faceoff_rows_untouched(nov17):
    assert nov17["Lian Bichsel"]["timeline"] == "2 weeks"
    assert nov17["Olli Maatta"]["timeline"] == "1 week"
    row = {"news_id": "1", "headline": "Faber left Saturday's game.", "date": "2026-09-27"}
    dfo.refresh([row | {"dfo_nhl_id": "", "dfo_player_id": "", "player": "Brock Faber"}], [], [], date(2026, 9, 29))
    assert dfo.parse("Faber left Saturday's game.", "2026-09-27")["news_status"] == "Left game"


def test_in_passing_and_chained_names():
    rows = nhlcom.parse_story(story([("Los Angeles Kings",
        f"{ent('Alex Turcotte', 8481572)} will take Panarin's place on the top line with "
        f"{ent('Alex Laferriere', 8482155)} and {ent('Adrian Kempe', 8477960)}."),
        ("New York Rangers",
         f"{ent('Dylan Garand', 8481580)} played 12 games since No. 1 goalie {ent('Igor Shesterkin', 8478048)} "
         "sustained a season-ending lower-body injury."),
        ("Ottawa Senators",
         f"{ent('Warren Foegele', 8477998)} will be out for an extended period after a knee-on-knee hit from "
         f"Vegas Golden Knights defenseman {ent('Jeremy Lauzon', 8478468)}.")]), STAMP)
    tags = tagged(rows)
    assert set(tags) == {"Alex Turcotte", "Dylan Garand", "Warren Foegele"}
    assert tags["Dylan Garand"][0] != "Out for season"
    assert tags["Warren Foegele"][0] == "Out indefinitely"


def test_co_subjects_get_their_own_injury_and_predicate():
    s = story([("Montreal Canadiens",
                f"Forward {ent('Josh Anderson', 8476981)} will be out about 3-4 weeks and defenseman "
                f"{ent('Mike Matheson', 8476875)} for about 2-3 weeks, each with a lower-body injury."),
               ("Philadelphia Flyers",
                f"Forward {ent('Travis Konecny', 8478439)} (lower body), and defensemen "
                f"{ent('Rasmus Ristolainen', 8477499)} (upper body) and {ent('Cam York', 8481546)} (upper body) "
                "are also unavailable and on injured reserve."),
               ("Ottawa Senators",
                f"Neither {ent('Jake Sanderson', 8483516)} (undisclosed) nor {ent('Artem Zub', 8482245)} (knee) "
                "are expected to play against the St. Louis Blues on Tuesday.")])
    tags = tagged(nhlcom.parse_story(s, STAMP))
    assert tags["Josh Anderson"] == ("Out", "Lower Body", "3-4 weeks")
    assert tags["Mike Matheson"] == ("Out", "Lower Body", "2-3 weeks")
    assert tags["Travis Konecny"][:2] == ("IR", "Lower Body")
    assert tags["Rasmus Ristolainen"][:2] == ("IR", "Upper Body")
    assert tags["Jake Sanderson"][:2] == ("Out", "Undisclosed")
    assert tags["Artem Zub"][:2] == ("Out", "Knee")


@pytest.mark.parametrize("sentence, status", [
    ("{p} practiced Thursday for the first time since undergoing a follow-up procedure in September.", "Practicing"),
    ("{p} returned to practice and is expected to play against the St. Louis Blues on Tuesday.", "Returning"),
    ("{p} returned to practice Monday after their No. 1 goalie missed a 4-3 win.", "Practicing"),
    ("{p} had three shots on goal in 16:52 after missing four games.", "Returning"),
    ("{p} is day to day and did not play at Toronto on Tuesday.", "Day-to-day"),
    ("{p} skated in a regular jersey, but the defenseman missed his fourth straight game.", "Out"),
    ("{p} did not practice with the Blues on Sunday.", "Other"),
    ("{p} is progressing but still not skating for the Islanders.", "Other"),
    ("{p} was recalled from Milwaukee of the AHL and is expected to back up Juuse Saros.", "Other"),
    ("{p} practiced with the Senators (6-3-0) on Monday and is expected to return Wednesday.", "Returning"),
    ("{p} did not return Saturday, but the coach said he will play on the road trip.", "Out"),
    ("{p} skated in a noncontact jersey Saturday, one week after the defenseman was injured.", "Practicing"),
])
def test_sentence_rules(sentence, status):
    rows = nhlcom.parse_story(story([("Ottawa Senators", sentence.format(p=ent("Jordan Example", 8400001)))]), STAMP)
    (got_status, injury, timeline), = tagged(rows).values()
    assert got_status == status
    assert injury not in ("Back", "6-3-0") and timeline == ""


def test_two_teams_in_one_part():
    s = story([("Colorado Avalanche", f"{ent('Nicolas Roy', 8480839)} is week to week.\n\n"
                                      f"## Montreal Canadiens\n\n{ent('Kirby Dach', 8481523)} is day to day.")])
    teams = {r["player"]: r["team"] for r in nhlcom.parse_story(s, STAMP)}
    assert teams == {"Nicolas Roy": "COL", "Kirby Dach": "MTL"}


def test_merge_replaces_an_edited_article_and_keeps_first_seen():
    v1 = story([("Dallas Stars", f"{ent('Miro Heiskanen', 8480036)} is questionable. … "
                                 f"{ent('Lian Bichsel', 8483425)} is out.")])
    rows, new, edited = nhlcom.merge([], [v1], "2026-11-20T21:05:00Z", {"8480036": "D"})
    assert (len(rows), new, edited) == (2, 2, 0)
    assert {r["position"] for r in rows if r["player"] == "Miro Heiskanen"} == {"D"}
    v2 = story([("Dallas Stars", f"{ent('Miro Heiskanen', 8480036)} will play. … "
                                 f"{ent('Thomas Harley', 8481581)} is out.")], updated="2026-11-20T22:30:00Z")
    rows, new, edited = nhlcom.merge(rows, [v2], "2026-11-20T22:35:00Z")
    by = {r["player"]: r for r in rows}
    assert (new, edited) == (1, 1)
    assert set(by) == {"Miro Heiskanen", "Thomas Harley"}      # Bichsel's note was removed
    assert by["Miro Heiskanen"]["headline"] == "Miro Heiskanen will play."
    assert by["Miro Heiskanen"]["scraped_at"] == "2026-11-20T21:05:00Z"
    assert by["Thomas Harley"]["scraped_at"] == "2026-11-20T22:35:00Z"
    assert by["Miro Heiskanen"]["updated_at"] == "2026-11-20T22:30:00Z"


class FakeClient:
    def __init__(self, listed, stories):
        self.listed, self.stories, self.fetched = listed, stories, []

    def recent_stories(self):
        return self.listed

    def story(self, slug):
        self.fetched.append(slug)
        return self.stories.get(slug)


def test_fetch_new_only_reads_new_or_edited_reports():
    today = date(2026, 11, 20)
    old = story([("Dallas Stars", f"{ent('Miro Heiskanen', 8480036)} is out.")],
                slug=nhlcom.slug_for(date(2026, 11, 19)), published="2026-11-19T20:00:00Z",
                updated="2026-11-19T21:00:00Z")
    stored, _, _ = nhlcom.merge([], [old], STAMP)
    listed = [{"slug": old["slug"], "contentDate": old["contentDate"], "lastUpdatedDate": "2026-11-19T21:00:00.000Z"},
              {"slug": "projected-lineup-oilers-vs-panthers", "contentDate": "2026-11-20T18:00:00Z"}]
    client = FakeClient(listed, {old["slug"]: old})
    assert nhlcom.fetch_new(client, stored, today) == []
    assert client.fetched == [nhlcom.slug_for(today)]   # today's not out yet (404); yesterday's unchanged
    listed[0]["lastUpdatedDate"] = "2026-11-19T23:10:00.000Z"
    edited = dict(old, lastUpdatedDate="2026-11-19T23:10:00.000Z")
    client = FakeClient(listed, {old["slug"]: edited})
    assert [s["slug"] for s in nhlcom.fetch_new(client, stored, today)] == [old["slug"]]


def test_slug_and_late_reports():
    assert nhlcom.slug_for(date(2026, 11, 3)) == "nhl-status-report-news-and-notes-november-3-2026"
    # The Nov. 13 report came out at 9:10 PM ET on Nov. 14: dated by when it was published.
    rows = nhlcom.parse_story(story([("Dallas Stars", f"{ent('Miro Heiskanen', 8480036)} is out.")],
                                    slug="nhl-status-report-news-and-notes-november-13-2026",
                                    published="2026-11-15T02:10:00Z"), STAMP)
    assert rows[0]["date"] == "2026-11-14"


def test_daily_faceoff_fetch_ignores_nhlcom_rows():
    nhl_row = {"news_id": "nhlcom:x:1", "published_at": "2026-11-20T21:00:00Z"}
    dfo_row = {"news_id": "5", "published_at": "2026-11-10T21:00:00Z"}

    class Pages:
        def __init__(self):
            self.n = 0

        def page(self, n):
            self.n = n
            created = f"2026-11-{20 - n:02d}T12:00:00.000Z"
            return [{"id": n, "createdAt": created}], 99

    pages = Pages()
    dfo.fetch_new(pages, [nhl_row, dfo_row], max_pages=20)
    assert pages.n > 5  # paged back toward Nov 10, not stopped by the newer NHL.com row
