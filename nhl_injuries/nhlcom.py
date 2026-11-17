"""NHL.com's daily "NHL Status Report": team-by-team injury and lineup notes.

The article (``nhl.com/news/nhl-status-report-news-and-notes-<month>-<d>-<yyyy>``)
comes out once a day, mid-afternoon or late at night, and some days not at all.
NHL.com's content API serves it as JSON: one Markdown part per team, headed
``## **Dallas Stars**``, with the team's notes separated by "…". Every player
mention is tagged ``<forge-entity title="Miro Heiskanen" slug="miro-heiskanen-8480036"
code="player">``, so items carry the NHL player id and link to CBS injuries as
reliably as Daily Faceoff's.

Each note becomes one row per player it's about, in the same schema as Daily
Faceoff news (``dfo.NEWS_COLUMNS``), so the app's feed, player and team pages show
both sources together. The note's first sentence is the headline and the rest is
the background. A player is a note's subject if he's named in its first sentence,
not in passing ("hit into the boards by X", "paired with X").

The article is edited after it's published. When its last-edited time changes,
all of its rows are replaced, keeping each player's first-seen time.

The status and injury tags come from the Daily Faceoff tagger (``dfo.parse``), run
on a per-player version of the headline (``tag_text``): "Broberg (lower body) and
Neighbours (upper body) could play..." is tagged once as "Broberg (lower body)
could play..." and once as "Neighbours (upper body) could play...".

This is NHL.com's own content system, not a documented API, so a failure is
only a warning, as it is for Daily Faceoff.
"""
from __future__ import annotations

import html
import re
import time
from datetime import date, timedelta

import requests

from .dfo import _RANGE, NEWS_COLUMNS, USER_AGENT, NewsError, _et_date, _utc
from .reference import TEAMS

API = "https://forge-dapi.d3.nhle.com/v2/content/en-us/stories"
SLUG_PREFIX = "nhl-status-report-news-and-notes-"
ARTICLE_URL = "https://www.nhl.com/news/{slug}"
SOURCE_NAME = "NHL.com Status Report"
ID_PREFIX = "nhlcom:"
LOOKBACK_DAYS = 3       # re-check reports published this recently for edits

_ENTITY = re.compile(r'<forge-entity\s+title="([^"]+)"\s+slug="[^"]*?-(\d{7})"\s+code="player"\s*>(.*?)</forge-entity>', re.S)
_ANY_TAG = re.compile(r"<[^>]+>")
_HEADER = re.compile(r"^\s*##\s*\**\s*(.+?)\s*\**\s*$", re.M)
# "(7 p.m. ET; SN, TVAS)", "(10:30 p.m. ET; ESPN+)": the game time and TV channels.
_TV = re.compile(r"\s*\(\d{1,2}(?::\d\d)?\s*[ap]\.m\.(?:\s*ET\b)?[^)]*\)")
_NOTE_SPLIT = re.compile(r"\s*(?:…|\.\.\.)\s*")
# Sentence ends: ". " or '." ' before a capital, but not "St. Louis", "T.J. Oshie", "Dr. ".
_SENTENCE_SPLIT = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"”’]))(?<!\bSt\.)(?<!\bDr\.)(?<!\bJr\.)(?<!\bvs\.)"
                             r"(?<!\b[A-Z]\.)\s+(?=[A-Z<\"“])")
# A sentence that opens with a tagged player ("Forward <X> was recalled") starts a new note.
_ROLE = r"(?:(?:Forwards?|Defensem[ae]n|Goalies?|Goaltenders?|Centers?|Wings?|Captain|Rookie)\s+)?"
_OPENS_WITH_PLAYER = re.compile(rf"^{_ROLE}<forge-entity")
# Role words NHL.com puts before a name ("defenseman Mike Matheson", "right wing Trent Frederic").
_ROLE_WORDS = r"(?:forwards?|defensem[ae]n|goalies?|goaltenders?|centers?|(?:left |right )?wings?|captain|rookie)"
# A player named after one of these is mentioned in passing, not the subject, and so is
# anyone chained to him ("with Alex Laferriere and Adrian Kempe", "With Pesce and X ill",
# "a hit from Vegas Golden Knights defenseman X").
_IN_PASSING = re.compile(
    r"(?i:\b(?:by|with|against|replace[sd]?|replacing|for|from|to|than|over|behind|alongside|of|after|"
    r"before|ahead of|including|beside|in place of|instead of|on a line with)\s+)"
    rf"(?:(?i:{_ROLE_WORDS}\s+)?[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*)*\s*(?:\([^)]*\))?\s*(?:,\s*and|,|and)\s+)*"
    rf"(?:[A-Z][\w'’.-]*\s+)*(?i:{_ROLE_WORDS}\s+)?$")
# "since No. 1 goalie X sustained...": what follows is about X.
_SINCE = re.compile(r"(?i:\b(?:since|when|while|as|because|until)\s+)(?:[\w.'’]+\s+){0,4}$")
_BY_NAME = {v[0].lower(): k for k, v in TEAMS.items()}
_BY_NAME["utah hockey club"] = "UTA"
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december"]


def slug_for(d: date) -> str:
    return f"{SLUG_PREFIX}{_MONTHS[d.month - 1]}-{d.day}-{d.year}"


def article_url(slug: str) -> str:
    return ARTICLE_URL.format(slug=slug)


def is_nhlcom(row: dict) -> bool:
    return str(row.get("news_id", "")).startswith(ID_PREFIX)


# ---------------------------------------------------------------- fetching

class Client:
    def __init__(self, session: requests.Session | None = None, pause: float = 0.5):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.pause = pause

    def get(self, url: str, params: dict | None = None) -> dict | None:
        """The JSON at ``url``, or None for a 404 (no report that day)."""
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=30)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                time.sleep(self.pause)
                return r.json()
            except (requests.RequestException, ValueError) as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise NewsError(f"NHL.com {url}: {last}")

    def recent_stories(self) -> list[dict]:
        data = self.get(API, {"tags.slug": "news", "$limit": 100}) or {}
        return list(data.get("items") or [])

    def story(self, slug: str) -> dict | None:
        return self.get(f"{API}/{slug}")


def recent_reports(client: Client, today: date, days: int = LOOKBACK_DAYS) -> dict[str, str]:
    """{slug: last-edited time} for Status Reports from the last ``days`` days.

    NHL.com's newest-100 news list is the main source; it shows a report as soon as
    it's out, under its real slug (the slug's date can be a day behind: the Nov. 13
    report came out late on Nov. 14). The date-built slugs for the last two days
    are added in case the list misses one; their edit time is unknown ("")."""
    cutoff = (today - timedelta(days=days)).isoformat()
    found: dict[str, str] = {}
    for s in client.recent_stories():
        slug = s.get("slug") or ""
        if slug.startswith(SLUG_PREFIX) and _et_date(s["contentDate"]) >= cutoff:
            found[slug] = s.get("lastUpdatedDate") or ""
    for k in range(2):
        found.setdefault(slug_for(today - timedelta(days=k)), "")
    return found


def fetch_new(client: Client, stored: list[dict], today: date) -> list[dict]:
    """Full stories for recent reports that are new or edited since last stored."""
    have: dict[str, str] = {}
    for r in stored:
        if is_nhlcom(r):
            have[r["source_url"]] = max(have.get(r["source_url"], ""), r["updated_at"])
    out = []
    for slug, edited in recent_reports(client, today).items():
        stored_at = have.get(article_url(slug))
        if edited and stored_at and _utc(edited) == stored_at:
            continue  # listed, unchanged since we stored it
        story = client.story(slug)
        if story is None:
            continue  # no report under this slug
        if stored_at and _utc(story["lastUpdatedDate"]) == stored_at:
            continue
        out.append(story)
    return out


# ---------------------------------------------------------------- parsing

def clean(s: str) -> str:
    """Markdown with entity tags -> plain text."""
    s = _ENTITY.sub(lambda m: m.group(1), s)
    s = _ANY_TAG.sub("", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)  # Markdown links: [Cameron Whitehead](https://...)
    s = re.sub(r"(?<!\w)[*_]+|[*_]+(?!\w)", "", s).replace("\xa0", " ")
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


def _subjects(first: str) -> tuple[list[tuple[str, str]], str]:
    """(name, NHL id) of the players a note's first sentence is about, in order, and
    the sentence cut short where it moves on to someone named in passing ("Garand
    played 12 games since No. 1 goalie Shesterkin sustained a season-ending injury"
    is cut before "since", so Garand isn't tagged out for the season)."""
    out: list[tuple[str, str]] = []
    about = clean(first)
    for m in _ENTITY.finditer(first):
        before = clean(first[:m.start()]) + " "
        passing = _IN_PASSING.search(before) or _SINCE.search(before)
        if passing:
            if out and passing.start() < len(about):
                about = before[:passing.start()].rstrip(" ,")
            continue
        if m.group(2) not in {pid for _, pid in out}:
            out.append((html.unescape(m.group(1)).strip(), m.group(2)))
    return out, about


def notes(story: dict) -> list[tuple[str, str, str, str, list[tuple[str, str]]]]:
    """(team, headline, background, subject text, subjects) for each note in the article."""
    out = []
    for part in story.get("parts") or []:
        if part.get("type") != "markdown":
            continue
        content = part.get("content") or ""
        heads = list(_HEADER.finditer(content))  # usually one team per part, sometimes two
        for k, m in enumerate(heads):
            team = _BY_NAME.get(clean(m.group(1)).lower(), "")
            body = _TV.sub("", content[m.end():heads[k + 1].start() if k + 1 < len(heads) else len(content)])
            out.extend(_team_notes(team, body))
    return out


def _team_notes(team: str, body: str) -> list[tuple[str, str, str, str, list[tuple[str, str]]]]:
    out = []
    for note in _NOTE_SPLIT.split(body):
        segment: list[str] = []
        segments = [segment]
        for s in _sentences(note):
            if segment and _OPENS_WITH_PLAYER.match(s):
                segment = []
                segments.append(segment)
            segment.append(s)
        for seg in segments:
            if not seg:
                continue
            subjects, about = _subjects(seg[0])
            if subjects:
                out.append((team, clean(seg[0]), clean(" ".join(seg[1:])), about, subjects))
    return out


def parse_story(story: dict, scraped_at: str) -> list[dict]:
    """News rows (``dfo.NEWS_COLUMNS`` raw fields) for one article."""
    slug = story["slug"]
    published = _utc(story["contentDate"])
    updated = _utc(story.get("lastUpdatedDate") or story["contentDate"])
    rows: dict[str, dict] = {}
    for team, headline, context, about, subjects in notes(story):
        for name, pid in subjects:
            nid = f"{ID_PREFIX}{slug}:{pid}"
            if nid in rows:  # named in two notes: keep both, as one item
                rows[nid]["context"] = " ".join(x for x in (rows[nid]["context"], headline, context) if x)
                continue
            rows[nid] = {
                "news_id": nid, "published_at": published, "updated_at": updated,
                "date": _et_date(story["contentDate"]), "player": name, "dfo_player_id": "",
                "dfo_nhl_id": pid, "position": "", "team": team, "team_is_current": False,
                "headline": headline, "context": context, "source_name": SOURCE_NAME,
                "subject_text": tag_text(about, name, [n for n, _ in subjects]),
                "source_url": article_url(slug), "breaking": False, "scraped_at": scraped_at,
            }
    return list(rows.values())


def merge(stored: list[dict], stories: list[dict], scraped_at: str,
          positions: dict[str, str] | None = None) -> tuple[list[dict], int, int]:
    """Replace each fetched article's rows. A player already in that article keeps his
    first scrape time. ``positions`` ({NHL id: position}) fills the position NHL.com
    leaves out. Returns (rows, new items, articles edited)."""
    positions = positions or {}
    by_id = {r["news_id"]: r for r in stored}
    new = edited = 0
    for story in stories:
        url = article_url(story["slug"])
        old = {nid: r for nid, r in by_id.items() if is_nhlcom(r) and r["source_url"] == url}
        if old:
            edited += 1
        for nid in old:
            del by_id[nid]
        for row in parse_story(story, scraped_at):
            row["position"] = positions.get(row["dfo_nhl_id"], "")
            if row["news_id"] in old:
                row["scraped_at"] = old[row["news_id"]]["scraped_at"] or scraped_at
            else:
                new += 1
            by_id[row["news_id"]] = {c: row.get(c, "") for c in NEWS_COLUMNS} | row
    rows = sorted(by_id.values(), key=lambda r: (r["published_at"], r["news_id"]), reverse=True)
    return rows, new, edited


def positions_from(news: list[dict], injuries: list[dict]) -> dict[str, str]:
    """{NHL id: position} from Daily Faceoff items, then CBS injuries."""
    out: dict[str, str] = {}
    for r in injuries:
        if r.get("nhl_id") and r.get("position"):
            out[r["nhl_id"]] = r["position"]
    for r in sorted(news, key=lambda r: r["published_at"]):  # newest wins
        if not is_nhlcom(r) and r.get("dfo_nhl_id") and r.get("position"):
            out[r["dfo_nhl_id"]] = r["position"]
    return out


# ---------------------------------------------------------------- tagging

def tag_text(sentence: str, player: str, co_subjects: list[str]) -> str:
    """The part of a note's first sentence about one player, for the status and injury
    tagger (stored as ``subject_text``).

    With co-subjects it keeps his own name and parenthetical plus the shared predicate,
    so a co-subject's injury isn't his ("Broberg (lower body) and Neighbours (upper body)
    could play" -> "Broberg (lower body) could play"). It stops at the first semicolon,
    after which NHL.com adds background ("will be out one week; the defenseman took his
    last shift with 8:05 left in the third"), and drops "who ..." asides."""
    h = sentence.split(";")[0]
    h = re.sub(r",\s+who\s[^,]*,", "", h)  # "Hallander, who had been scratched..., played"
    names = [n for n in co_subjects if n in h]
    if player not in h or len(names) < 2:
        return h.strip()
    # Split into one chunk per subject: name, own parenthetical, then his predicate if he
    # has one ("Anderson will be out 3-4 weeks and defenseman Matheson for 2-3 weeks").
    # A subject with no predicate of his own ("Broberg (lower body) and") takes the next one's.
    starts = sorted((h.index(n), n) for n in names)
    chunks = []
    for k, (st, name) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(h)
        m = re.match(r"\s*(\([^)]*\))?", h[st + len(name):end])
        pred = re.sub(rf"(?:,|\band\b|\b{_ROLE_WORDS}|\s)+$", "", h[st + len(name) + m.end():end], flags=re.I)
        chunks.append((name, m.group(1) or "", pred.strip()))
    prefix = re.sub(rf"\b{_ROLE_WORDS}\s*$", "", h[:starts[0][0]], flags=re.I)
    i = next(k for k, c in enumerate(chunks) if c[0] == player)
    pred = next((c[2] for c in chunks[i:] if len(re.findall(r"\w+", c[2])) >= 2), chunks[-1][2])
    # A closing ", each with a lower-body injury" applies to everyone.
    shared = re.search(r",?\s*\b(?:each|both|all)\b(?! of)[^;]*$", chunks[-1][2])
    if shared and pred != chunks[-1][2]:
        pred = f"{pred}{shared.group(0)}"
    return " ".join(x for x in (f"{prefix}{player}", chunks[i][1], pred) if x).strip()


def tag_texts(news: list[dict]) -> dict[str, tuple[str, bool]]:
    """{news_id: (text to tag, whether he's the note's only subject)} for every NHL.com row."""
    count: dict[tuple[str, str], int] = {}
    for r in news:
        if is_nhlcom(r):
            count[(r["source_url"], r["headline"])] = count.get((r["source_url"], r["headline"]), 0) + 1
    return {r["news_id"]: (r.get("subject_text") or r["headline"], count[(r["source_url"], r["headline"])] == 1)
            for r in news if is_nhlcom(r)}


# NHL.com writes in full sentences ("did not play", "could return Tuesday") where Daily
# Faceoff writes short headlines, so a few rules run before and after Daily Faceoff's.
_QUOTES = re.compile(r"[\"“”]")
# "did not practice" is not practice news; drop it so it can't read as "Practicing".
_NO_PRACTICE = re.compile(r"\b(?:did not|didn't|does not|won't|will not)\s+(?:practice|skate)\b|"
                          r"\b(?:was not|wasn't) on the ice\b|\bnot (?:yet )?skating\b", re.I)
# "expected to back up Saros" is not a back injury, and "the Senators (6-3-0)" is not an injury type.
_BACKUP = re.compile(r"\bback(?:ed|ing)? up\b", re.I)
_RECORD = re.compile(r"\s*\(\d+-\d+(?:-\d+)?\)")
# ", which the forward missed after aggravating a prior injury" is background.
_WHICH = re.compile(r",\s+which\s[^,;]*")


def _neutral(text: str) -> str:
    return _WHICH.sub("", _RECORD.sub("", _BACKUP.sub("backup", text)))
# "returned to practice" is practice news, not "Returning"; "and is expected to play" still is.
_BACK_AT_PRACTICE = re.compile(r"\b(?:returned|was back) (?:to|at) (?:[\w'’.-]+ )?practice\b", re.I)
# History, not news: "practiced Thursday for the first time since ... undergoing a
# procedure in September", "skated, one week after he was injured".
_HISTORY = re.compile(r"\b(?:for the first time )?since (?:sustaining|suffering|having|undergoing|being|getting|he)\b[^,;]*|"
                      r"\bafter (?!missing)[^,;]*?\bmissed\b[^,;]*|"  # "practiced after their No. 1 goalie missed a win"
                      rf"(?:{_RANGE.pattern})\s+(?:after|before|since)\b[^,;]*", re.I)
# Checked first, whatever Daily Faceoff's rules say.
_FIRST = [(s, re.compile(p, re.I)) for s, p in [
    ("Out", r"^\W*neither\b"),  # "Neither Sanderson nor Zub are expected to play"
    ("Other", r"\bNHL debut\b"),  # a call-up, not a return from injury
    ("Game-time decision", r"\bcould (?:return|play|be back|be available|rejoin|dress|be in the lineup)\b|"
                           r"\b(?:is|are) (?:also )?possible\b|\bpossible to play\b"),
    ("Returning", r"\b(?:played|returned|dressed) after (?:missing|sitting out|being)\b|"
                  r"\bexpects? (?:him|the \w+) to play\b"),
]]
# He wasn't in the lineup. Overrides only the weak statuses: "skated Monday but did not
# play" is Out, "is day to day and did not play" stays Day-to-day.
_ABSENT = re.compile(r"\b(?:did not|didn't) (?:play|dress)\b|\bnot in the lineup\b|"
                     r"\bmissed (?!practice|the morning skate|morning skate)|"
                     r"\b(?:was|is|were|are) (?:also )?(?:unavailable|not available|unlikely)\b", re.I)
_WEAK = ("Other", "Practicing", "Returning", "Left game")
# Only when nothing else matched, in this order.
_FALLBACK = [(s, re.compile(p, re.I)) for s, p in [
    ("Returning", r"\bmade his season debut\b|\b(?:played|dressed|started) (?:for|in|against)\b|"
                  r"\bafter missing\b|\bwill (?:also|each|both) (?:return|play)\b|\b(?:was|is) in the lineup\b|"
                  r"\b(?:is|he['’]s|he is) going to play\b"),
    ("Out", r"\bmiss(?:ed|es|ing)\b|\baway from the team\b|\bgoing to be out\b"),
    ("Practicing", r"\bconditioning (?:loan|assignment|stint)\b|\bdrills\b|\btook (?:some )?shots\b"),
    ("Game-time decision", r"\bcould make his season debut\b|\bnearing (?:a |his )?(?:return|season debut)\b|"
                           r"\bcould come as soon as\b|\bunsure\b|\bnot sure\b"),
]]
_BODY_INJURIES = {"Upper Body", "Lower Body", "Undisclosed", "Concussion", "Head", "Neck", "Jaw", "Eye", "Face",
                  "Knee", "Achilles", "Ankle", "Foot", "Groin", "Hamstring", "Hip", "Abdomen", "Back", "Chest",
                  "Ribs", "Shoulder", "Collarbone", "Elbow", "Forearm", "Wrist", "Thumb", "Finger", "Hand", "Arm",
                  "Leg", "Toe", "Blood Clot", "Illness"}
# "did not return Saturday" (to the lineup) is not "left the game".
_NOT_LEFT = re.compile(r"\bdid not return (?:on )?(?:sunday|monday|tuesday|wednesday|thursday|friday|saturday|tonight)\b", re.I)


def parse(text: str, row: dict, solo: bool = True) -> dict:
    """``dfo.parse`` on the per-player text, with the NHL.com rules above. If the
    headline names no injury and he's the note's only subject, the injury comes from
    the background's first sentence ("Their top defenseman missed five games with an
    upper-body injury"), unless that sentence lists other players' injuries."""
    from . import dfo
    text = _NO_PRACTICE.sub("", _QUOTES.sub("", text))
    text = _BACK_AT_PRACTICE.sub("practiced", text)
    text = _HISTORY.sub("", _neutral(text))
    out = dfo.parse(text, row["date"])
    if re.search(r"\d|,", out["injury"]):  # "(10 starts, two in relief)" is not an injury
        out["injury"] = out["category"] = ""
    first = next((s for s, rx in _FIRST if rx.search(text)), None)
    if first:
        out["news_status"] = first
    elif out["news_status"] in _WEAK and _ABSENT.search(text):
        out["news_status"] = "Out"
    elif out["news_status"] == "Other":
        out["news_status"] = next((s for s, rx in _FALLBACK if rx.search(text)), "Other")
    if out["news_status"] == "Left game" and (out["timeline"] or _NOT_LEFT.search(text)):
        out["news_status"] = "Out"  # "will be out at least a week after he left Tuesday's game"
    if out["news_status"] == "Game-time decision" and out["timeline"]:
        out["news_status"] = "Out"  # "could return to the lineup within two weeks"
    first_bg = _sentences(row.get("context") or "")[:1]
    if not out["injury"] and solo and first_bg and "(" not in first_bg[0]:
        injury = dfo.parse_injury(_neutral(first_bg[0]))
        if injury in _BODY_INJURIES:
            out["injury"] = injury
            out["category"] = dfo.injury_category(injury)
    return out
