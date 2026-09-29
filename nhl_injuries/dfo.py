"""Daily Faceoff injury news: timestamped, sourced updates to go with the CBS report.

CBS says who is on the report; Daily Faceoff says what just happened ("underwent
surgery", "left Thursday's game", "will return Saturday"), minutes after the
beat reporter tweets it. Each page of
``dailyfaceoff.com/hockey-player-news/injuries/<n>`` embeds its 20 items as JSON
in the Next.js ``__NEXT_DATA__`` script, newest first, back to 2011.

Two quirks shape how the items are stored:

* ``teamAbbreviation`` is the player's team *now* (last season's playoff items for
  players who have since left show ``FA``), so ``team`` is recorded when an item is
  first scraped and never overwritten. Backfilled items get the team at backfill
  time; ``team_is_current`` marks those.
* Most items are edited within the hour (typos, the background paragraph), so a
  known id is refreshed rather than skipped.

The headline is parsed into a status (``news_status``), a body part, a surgery flag
and, where it gives one ("3-to-5 months", "at least one month", "re-evaluated in
eight weeks"), a return window. Each item is then linked to an NHL player id and to
the CBS injury it belongs to.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta, timezone

import requests

from . import nhl
from .nhl import name_key
from .reference import ET, TEAMS, injury_category, season_of

BASE_URL = "https://www.dailyfaceoff.com/hockey-player-news/injuries"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
MAX_PAGES = 30          # a normal run needs 1-2; this bounds a run after a long gap
OVERLAP_HOURS = 36      # keep paging until this far behind the newest stored item (catches edits)
LINK_BEFORE_DAYS = 5    # news can come a few days before CBS lists the player ...
LINK_AFTER_DAYS = 3     # ... and a little after CBS drops him (the "will return" item)

# Raw fields, as scraped. Derived fields are recomputed every run (see ``refresh``).
RAW_COLUMNS = ["news_id", "published_at", "updated_at", "date", "player", "dfo_player_id",
               "dfo_nhl_id", "position", "team", "team_is_current", "headline", "context",
               "source_name", "source_url", "breaking", "scraped_at"]
DERIVED_COLUMNS = ["nhl_id", "matched_by", "injury", "category", "news_status", "surgery",
                   "timeline", "return_earliest", "return_latest", "injury_id"]
NEWS_COLUMNS = RAW_COLUMNS + DERIVED_COLUMNS

# news_status values, in precedence order (the first match wins).
STATUSES = ["Out for season", "LTIR", "IR", "Injured non-roster", "Activated", "Out indefinitely",
            "Month-to-month", "Week-to-week", "Left game", "Out", "Game-time decision",
            "Day-to-day", "Being evaluated", "Returning", "Practicing", "Other"]
# Statuses that say he's playing or close to it (used by the app and the bot).
GOOD_NEWS = ("Activated", "Returning", "Practicing")
# bad: out; warn: might play; good: playing or close. "Other" has no tone.
TONE = {
    **dict.fromkeys(["Out for season", "LTIR", "IR", "Injured non-roster", "Out indefinitely",
                     "Month-to-month", "Week-to-week", "Left game", "Out"], "bad"),
    **dict.fromkeys(["Game-time decision", "Day-to-day", "Being evaluated"], "warn"),
    **dict.fromkeys(GOOD_NEWS, "good"),
}

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


class NewsError(RuntimeError):
    pass


# ---------------------------------------------------------------- fetching

def page_url(page: int) -> str:
    # ?page=N is ignored server-side; pagination is by path.
    return BASE_URL if page <= 1 else f"{BASE_URL}/{page}"


def parse_page(html: str) -> tuple[list[dict], int]:
    """(items, last_page) from one page's embedded JSON."""
    m = _NEXT_DATA.search(html)
    if not m:
        raise NewsError("Daily Faceoff page has no __NEXT_DATA__ block (layout changed?)")
    try:
        data = json.loads(m.group(1))["props"]["pageProps"]["data"]
        return list(data["data"]), int(data.get("lastPage") or 0)
    except (KeyError, TypeError, ValueError) as e:
        raise NewsError(f"Daily Faceoff JSON not in the expected shape: {e}") from e


class Client:
    def __init__(self, session: requests.Session | None = None, pause: float = 1.0):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        self.pause = pause

    def page(self, n: int) -> tuple[list[dict], int]:
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self.session.get(page_url(n), timeout=30)
                r.raise_for_status()
                time.sleep(self.pause)
                return parse_page(r.text)
            except requests.RequestException as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise NewsError(f"Daily Faceoff page {n}: {last}")


def _clean(s) -> str:
    # The feed has mojibake apostrophes ("Saturday�s") and stray blank lines.
    return re.sub(r"\s+", " ", str(s or "").replace("�", "'")).strip()


def _et_date(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ET).date().isoformat()


def _utc(ts: str) -> str:
    """'2026-09-29T16:22:05.607Z' -> '2026-09-29T16:22:05Z'."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")


def to_row(item: dict, scraped_at: str, team_is_current: bool = False) -> dict:
    team = item.get("teamAbbreviation") or ""
    return {
        "news_id": str(item["id"]),
        "published_at": _utc(item["createdAt"]),
        "updated_at": _utc(item.get("updatedAt") or item["createdAt"]),
        "date": _et_date(item["createdAt"]),
        "player": _clean(item.get("playerName")),
        "dfo_player_id": str(item.get("playerId") or ""),
        "dfo_nhl_id": str(item.get("playerFiveVFiveId") or ""),
        "position": item.get("playerPosition") or "",
        "team": team if team in TEAMS else "",
        "team_is_current": team_is_current,
        "headline": _clean(item.get("details")),
        "context": _clean(item.get("fantasyDetails")),
        "source_name": _clean(item.get("sourceName")),
        "source_url": item.get("sourceUrl") or "",
        "breaking": bool(item.get("breakingNews")),
        "scraped_at": scraped_at,
    }


def merge(stored: list[dict], items: list[dict], scraped_at: str, backfill: bool = False) -> tuple[list[dict], int, int]:
    """Fold scraped items into the stored rows. New ids are added; known ids get the
    edited text but keep the team and scrape time of their first sighting.
    Returns (rows, new, edited)."""
    by_id = {r["news_id"]: r for r in stored}
    new = edited = 0
    for item in items:
        row = to_row(item, scraped_at, team_is_current=backfill)
        old = by_id.get(row["news_id"])
        if old is None:
            by_id[row["news_id"]] = row
            new += 1
            continue
        if row["updated_at"] != old["updated_at"]:
            edited += 1
        keep = {c: old[c] for c in ("team", "team_is_current", "scraped_at") if old.get(c) not in (None, "")}
        by_id[row["news_id"]] = {**old, **row, **keep}
    rows = sorted(by_id.values(), key=lambda r: (r["published_at"], r["news_id"]), reverse=True)
    return rows, new, edited


def fetch_new(client: Client, stored: list[dict], max_pages: int = MAX_PAGES) -> list[dict]:
    """Items from page 1 back until OVERLAP_HOURS behind the newest stored item."""
    newest = max((r["published_at"] for r in stored), default="")
    stop = ""
    if newest:
        stop = (datetime.fromisoformat(newest.replace("Z", "+00:00"))
                - timedelta(hours=OVERLAP_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: list[dict] = []
    for n in range(1, max_pages + 1):
        items, last_page = client.page(n)
        out.extend(items)
        if not items or n >= last_page or (stop and _utc(items[-1]["createdAt"]) < stop):
            break
    return out


# ---------------------------------------------------------------- headline parsing

_WORDNUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
            "a couple of": 2, "a couple": 2, "a few": 3, "several": 3}
_NUM = r"(\d+|a couple(?: of)?|a few|several|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_UNIT = r"(day|week|month)s?"
_RANGE = re.compile(rf"\b{_NUM}(?:\s*(?:-|to|-to-|–|or)\s*{_NUM})?(?:\s*|-)(?:more\s+|additional\s+)?{_UNIT}\b", re.I)
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30}

# (status, pattern) in precedence order; matched against the lower-cased headline.
_STATUS_RULES = [
    ("Out for season", r"out for the (?:rest of the |remainder of the )?season|season-ending|"
                       r"(?:rest|remainder) of the (?:\d{4}-\d{2} )?(?:regular )?season|"
                       r"not expected to return this season"),
    ("LTIR", r"\bltir\b|long-term injured reserve"),
    ("Activated", r"activated|off (?:of )?(?:injured reserve|ir\b|ltir)|removed from (?:ir|injured reserve)|"
                  r"reinstated"),
    ("IR", r"\bon (?:the )?(?:ir|injured reserve)\b|placed on (?:the )?(?:ir|injured reserve)|"
           r"to (?:ir|injured reserve)\b"),
    ("Injured non-roster", r"non-roster"),
    ("Out indefinitely", r"indefinitely|out for an extended|extended period|out long-term|no timeline"),
    ("Month-to-month", r"month-to-month|month to month"),
    ("Week-to-week", r"week-to-week|week to week"),
    ("Left game", r"\b(?:left|exited)\b.*\b(?:game|period|contest|practice|warmups?|morning skate)\b|"
                  r"did not return|will not return (?:to|for|in) (?:the|tonight|game|\w+'s game)"),
    ("Out", r"\bwill not \w+|not expected to|not (?:be )?available|remains? out|miss some time|won't (?:play|dress|suit up|be)|\bwill (?:be )?miss|is out\b|"
            r"will be out|not expected to (?:play|dress|suit|be in)|ruled out|\bscratch|out of the lineup|"
            r"\bwill sit\b|is doubtful|unlikely to play|won't return|\bout (?:vs|against|for|on|tonight|until|"
            r"saturday|sunday|monday|tuesday|wednesday|thursday|friday)\b|expected to miss|"
            r"\bmiss(?:es)? (?:the|at least)|sidelined|re-?evaluated in|kept out|failed (?:his|a) physical|"
            r"weeks of recovery|shut down|underwent|undergo|had surgery"),
    ("Game-time decision", r"game-time dec|game time dec|\bgtd\b|questionable|possibility|likely to|maybe|"
                           r"hopeful(?:ly)? to|chance to (?:play|return)|uncertain|probable|trending towards?"),
    ("Day-to-day", r"day-to-day|day to day"),
    ("Being evaluated", r"evaluat|further (?:testing|treatment)|specialist|concussion protocol|diagnosed|"
                        r"banged up|\bmri\b|tests?\b"),
    ("Returning", r"\bwill (?:return|play|dress|start|be back|make his|draw back|rejoin|suit up|be in|be okay)|"
                  r"expected (?:to (?:play|return|dress|start|draw|make|be (?:back|ready|available))|back)|"
                  r"\bcleared\b|\bis back\b|back in the lineup|return to the lineup|\brejoin|is available|"
                  r"good to go|is set to return|returns? to action|listed as active|ready (?:to play|for)|"
                  r"able to return|expects to be ready|\breturned\b|targeting a return"),
    ("Practicing", r"practic|\bskat(?:e|ed|ing)\b|full participant|took (?:full )?part|non-contact|"
                   r"no-contact|morning skate|warmups|on the ice|camp debut|limited participant|travel with"),
]
_STATUS_RES = [(s, re.compile(p)) for s, p in _STATUS_RULES]

# "Faber (upper body) ...": the parenthesis right after the name, when there is one.
_PAREN = re.compile(r"^[^(]{0,60}\(([^)]{2,40})\)")
# Body-part vocabulary, most specific first: (pattern, CBS-style injury type).
_BODY = [(re.compile(p, re.I), t) for p, t in [
    (r"upper[- ]body", "Upper Body"), (r"lower[- ]body", "Lower Body"), (r"\bundi[a-z]*s[a-z]*\b", "Undisclosed"),
    (r"concussion", "Concussion"), (r"skull|\bhead\b", "Head"), (r"\bneck\b", "Neck"),
    (r"\bjaw\b", "Jaw"), (r"\beye\b|orbital", "Eye"), (r"\bface\b|facial", "Face"),
    (r"\bacl\b|\bmcl\b|menisc|\bknee", "Knee"), (r"achilles", "Achilles"), (r"ankle", "Ankle"),
    (r"\bfoot\b|\bfeet\b", "Foot"), (r"groin|adductor", "Groin"), (r"hamstring", "Hamstring"),
    (r"\bhip\b|labral|labrum", "Hip"), (r"sports hernia|\bcore\b|abdom|oblique|middle[- ]body", "Abdomen"),
    (r"\bback\b(?! (?:in|to|on|for|into|with)\b)|vertebra|spine|spinal", "Back"),
    (r"pectoral|\bpec\b|chest", "Chest"), (r"\bribs?\b", "Ribs"), (r"shoulder", "Shoulder"),
    (r"collarbone|clavicle", "Collarbone"), (r"elbow", "Elbow"), (r"forearm", "Forearm"),
    (r"wrist", "Wrist"), (r"thumb", "Thumb"), (r"finger", "Finger"), (r"\bhand\b", "Hand"),
    (r"\barm\b|bicep|tricep", "Arm"), (r"\bleg\b|\bshin\b|\bcalf\b|thigh|\bquad", "Leg"),
    (r"\btoe\b", "Toe"), (r"blood clot", "Blood Clot"), (r"illness|\bflu\b|\bsick", "Illness"),
    (r"suspen", "Suspension"), (r"visa|immigration", "Visa"), (r"paternity", "Paternity"),
    (r"personal|family", "Personal"), (r"maint?[ae]nance|\brest\b", "Rest"),
    (r"contract", "Contract Dispute"),
]]


def parse_status(headline: str) -> str:
    h = (headline or "").lower()
    for status, rx in _STATUS_RES:
        if rx.search(h):
            return status
    return "Other"


def parse_injury(headline: str) -> str:
    """CBS-style injury type: from the parenthesis after the name if there is one,
    else the first body part the headline mentions ("underwent shoulder surgery")."""
    h = headline or ""
    m = _PAREN.search(h)
    for text in ([m.group(1)] if m else []) + [h]:
        for rx, injury in _BODY:
            if rx.search(text):
                return injury
    return m.group(1).strip().title() if m and not m.group(1).isupper() else ""


def _num(s: str) -> int:
    s = s.lower()
    return int(s) if s.isdigit() else _WORDNUM.get(s, 0)


def parse_timeline(headline: str, published: date) -> tuple[str, str, str]:
    """(timeline text, earliest return, latest return) from phrases like "out 4-8 weeks",
    "another 3-to-5 months", "at least one month", "re-evaluated in eight weeks".
    Dates are counted from the day of the item; blank when the headline has none."""
    h = headline or ""
    if re.search(r"day-to-day|week-to-week|month-to-month", h, re.I) and not _RANGE.search(
            re.sub(r"(?:day|week|month)-to-(?:day|week|month)", "", h, flags=re.I)):
        return "", "", ""
    for m in _RANGE.finditer(h):
        before = h[max(0, m.start() - 40):m.start()].lower()
        # "in his first two games", "played three weeks ago" are not timelines.
        if re.search(r"\b(?:ago|last|first|past|since|previous|over the)\s*$", before) or \
                re.search(r"^\s*ago", h[m.end():m.end() + 6].lower()):
            continue
        lo, hi, unit = _num(m.group(1)), _num(m.group(2) or m.group(1)), m.group(3).lower()
        if not lo:
            continue
        hi = max(hi, lo)
        days = _UNIT_DAYS[unit]
        at_least = bool(re.search(r"at least|minimum|a minimum of|no sooner", before))
        text = (f"{lo}-{hi} {unit}s" if hi != lo else f"{lo} {unit}{'s' if lo != 1 else ''}")
        if re.search(r"re-?evaluat|reassess|re-?examin", before + h[m.end():m.end() + 20].lower()):
            text = f"re-evaluated in {text}"
        elif at_least:
            text = f"at least {text}"
        earliest = published + timedelta(days=lo * days)
        latest = "" if at_least else (published + timedelta(days=hi * days)).isoformat()
        return text, earliest.isoformat(), latest
    return "", "", ""


def parse(headline: str, published: str) -> dict:
    injury = parse_injury(headline)
    timeline, earliest, latest = parse_timeline(headline, date.fromisoformat(published))
    status = parse_status(headline)
    if timeline and status in ("Other", "Being evaluated"):
        status = "Out"
    return {"injury": injury, "category": injury_category(injury) if injury else "",
            "news_status": status,
            "surgery": bool(re.search(r"surger|operation|procedure", headline or "", re.I)),
            "timeline": timeline, "return_earliest": earliest, "return_latest": latest}


# ---------------------------------------------------------------- linking

def _name_index(injuries: list[dict], players: list[dict]) -> dict[str, set[str]]:
    idx: dict[str, set[str]] = {}
    for r in (*players, *injuries):
        if r.get("nhl_id"):
            idx.setdefault(name_key(r["player"]), set()).add(r["nhl_id"])
    return idx


def player_cache_key(dfo_player_id: str) -> str:
    """Key for a Daily Faceoff player in data/nhl/players.csv (CBS players use their CBS id)."""
    return f"dfo:{dfo_player_id}"


def resolve_ids(news: list[dict], injuries: list[dict], players: list[dict]) -> None:
    """``nhl_id`` from Daily Faceoff when it has one (~95%; it often leaves goalies
    out), else the player's other items, else a unique name match in our data, else
    the NHL.com match cached by ``sync_players``."""
    by_dfo: dict[str, str] = {}
    for r in news:
        if r["dfo_nhl_id"] and r["dfo_player_id"]:
            by_dfo[r["dfo_player_id"]] = r["dfo_nhl_id"]
    # Name matches only against CBS-tracked players; dfo: cache rows are matched by id below.
    names = _name_index(injuries, [p for p in players if not p["key"].startswith("dfo:")])
    cached = {p["key"]: p["nhl_id"] for p in players if p["key"].startswith("dfo:") and p["nhl_id"]}
    for r in news:
        if r["dfo_nhl_id"]:
            r["nhl_id"], r["matched_by"] = r["dfo_nhl_id"], "dfo"
        elif r["dfo_player_id"] in by_dfo:
            r["nhl_id"], r["matched_by"] = by_dfo[r["dfo_player_id"]], "dfo (other item)"
        elif len(names.get(name_key(r["player"]), ())) == 1:
            r["nhl_id"], r["matched_by"] = next(iter(names[name_key(r["player"])])), "name"
        elif player_cache_key(r["dfo_player_id"]) in cached:
            r["nhl_id"], r["matched_by"] = cached[player_cache_key(r["dfo_player_id"])], "nhl.com"
        else:
            r["nhl_id"], r["matched_by"] = "", "unmatched"


def sync_players(client: nhl.Client, news: list[dict], players: list[dict], today: date) -> list[dict]:
    """Look up NHL.com ids for Daily Faceoff players still unmatched after ``refresh``
    (rosters, then the player search), cached in players.csv under ``dfo:<id>`` keys
    and retried weekly like the CBS players."""
    known = {p["key"]: dict(p) for p in players}
    retry_before = (today - timedelta(days=nhl.RECHECK_DAYS)).isoformat()
    todo: dict[str, dict] = {}
    for r in news:  # newest first, so the latest team is tried
        key = player_cache_key(r["dfo_player_id"])
        if r["matched_by"] != "unmatched" or not r["dfo_player_id"] or key in todo:
            continue
        p = known.get(key)
        if p is None or (not p["nhl_id"] and p["checked"] < retry_before):
            todo[key] = r
    if not todo:
        return players
    seasons = sorted({nhl.season_id(season_of(r["date"])) for r in todo.values()})
    matcher = nhl.PlayerMatcher(client, seasons)
    for key, r in todo.items():
        hit, how = matcher.match(r["player"], r["team"], r["position"])
        known[key] = {"key": key, "player": r["player"], "team": r["team"],
                      "nhl_id": hit["nhl_id"] if hit else "",
                      "birth_date": hit.get("birth_date", "") if hit else "",
                      "nhl_position": hit.get("position", "") if hit else "",
                      "matched_by": how, "checked": today.isoformat()}
    return sorted(known.values(), key=lambda p: p["key"])


def link_injuries(news: list[dict], injuries: list[dict], today: date) -> None:
    """``injury_id`` of the CBS injury each item is about: same player, dated from a
    few days before CBS listed him to a few days after he came off. The nearest
    injury wins when windows overlap."""
    by_player: dict[str, list[dict]] = {}
    for i in injuries:
        if i.get("nhl_id"):
            by_player.setdefault(i["nhl_id"], []).append(i)
    for r in news:
        best, gap = "", None
        d = date.fromisoformat(r["date"])
        for i in by_player.get(r["nhl_id"], []):
            start = date.fromisoformat(i["first_seen"])
            end = date.fromisoformat(i["return_date"]) if i.get("return_date") else today
            if start - timedelta(days=LINK_BEFORE_DAYS) <= d <= end + timedelta(days=LINK_AFTER_DAYS):
                g = 0 if start <= d <= end else min(abs((d - start).days), abs((d - end).days))
                if gap is None or g < gap:
                    best, gap = i["injury_id"], g
        r["injury_id"] = best


def refresh(news: list[dict], injuries: list[dict], players: list[dict], today: date) -> list[dict]:
    """Recompute every derived column. Cheap, and keeps links right as CBS
    injuries open and close."""
    for r in news:
        r.update(parse(r["headline"], r["date"]))
    resolve_ids(news, injuries, players)
    link_injuries(news, injuries, today)
    return news
