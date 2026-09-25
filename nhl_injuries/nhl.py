"""NHL.com data used to check the injury report against what actually happened:
player ids and birth dates, the league schedule, and who dressed in each game.

Everything comes from the public api-web.nhle.com endpoints (no key needed) and is
cached under data/nhl/, so a normal run only fetches the few games played since the
last one.
"""
from __future__ import annotations

import re
import time
import unicodedata
from datetime import date, timedelta

import requests

from .reference import TEAMS

API = "https://api-web.nhle.com/v1"
SEARCH = "https://search.d3.nhle.com/api/v1/search/player"
COUNTED_TYPES = ("2", "3")        # regular season and playoffs; preseason games don't count
DONE_STATES = ("OFF", "FINAL")
RECHECK_DAYS = 7                  # retry unmatched players this often

GAME_COLUMNS = ["game_id", "season", "game_type", "date", "away", "home", "state"]
APPEARANCE_COLUMNS = ["game_id", "date", "team", "nhl_id"]
PLAYER_COLUMNS = ["key", "player", "team", "nhl_id", "birth_date", "nhl_position",
                  "matched_by", "checked"]


class NHLError(RuntimeError):
    pass


class Client:
    def __init__(self, session: requests.Session | None = None, pause: float = 0.05):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = "nhl-injury-database/1.0"
        self.pause = pause

    def get(self, url: str, **params) -> dict | list | None:
        """JSON from the API; None for a 404. Retries transient failures."""
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params or None, timeout=20)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                time.sleep(self.pause)
                return r.json()
            except (requests.RequestException, ValueError) as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise NHLError(f"{url}: {last}")


def season_id(label: str) -> str:
    """'2025-26' -> '20252026'."""
    start = int(label[:4])
    return f"{start}{start + 1}"


def name_key(s: str) -> str:
    """Accent-, case- and punctuation-free name for matching (Stützle -> stutzle)."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", s.lower())


def player_key(inj: dict) -> str:
    """Key shared by all of a player's injury rows: CBS id, else the name (old imports)."""
    return inj["player_id"] or "name:" + name_key(inj["player"])


def _same_position(cbs: str, nhl: str) -> bool:
    group = lambda p: {"G": "G", "D": "D"}.get((p or "")[:1].upper(), "F")  # noqa: E731
    return not cbs or not nhl or group(cbs) == group(nhl)


# ---------------------------------------------------------------- players

class PlayerMatcher:
    """CBS name + team -> NHL player. Tries the listed team's roster first, then
    every roster (for players who moved), then the NHL player search (retired or
    unsigned players are on no roster)."""

    def __init__(self, client: Client, season_ids: list[str]):
        self.client = client
        self.season_ids = sorted(set(season_ids), reverse=True)
        self._rosters: dict[tuple[str, str], list[dict]] = {}

    def roster(self, team: str, season: str) -> list[dict]:
        if (team, season) not in self._rosters:
            data = self.client.get(f"{API}/roster/{team}/{season}") or {}
            self._rosters[team, season] = [
                {"nhl_id": str(p["id"]), "first": p["firstName"]["default"],
                 "last": p["lastName"]["default"], "team": team,
                 "position": p.get("positionCode", ""), "birth_date": p.get("birthDate", "")}
                for grp in ("forwards", "defensemen", "goalies") for p in data.get(grp, [])]
        return self._rosters[team, season]

    @staticmethod
    def _pick(cands: list[dict], position: str) -> dict | None:
        cands = [c for c in cands if _same_position(position, c["position"])]
        return cands[0] if len({c["nhl_id"] for c in cands}) == 1 else None

    def match(self, name: str, team: str, position: str) -> tuple[dict | None, str]:
        full = name_key(name)
        seasons = ["current", *self.season_ids]
        if team in TEAMS:
            for season in seasons:
                pool = self.roster(team, season)
                hit = self._pick([c for c in pool if name_key(c["first"] + c["last"]) == full], position)
                if hit:
                    return hit, "roster"
                # Nicknames (CBS "Alex", NHL "Alexander"): same team, same last name.
                hit = self._pick([c for c in pool if name_key(c["last"])
                                  and full.endswith(name_key(c["last"]))
                                  and full[:1] == name_key(c["first"])[:1]], position)
                if hit:
                    return hit, "roster (nickname)"
        for season in seasons:
            pool = [c for t in TEAMS for c in self.roster(t, season)]
            hit = self._pick([c for c in pool if name_key(c["first"] + c["last"]) == full], position)
            if hit:
                return hit, "roster (other team)"
        return self._search(name, team, position)

    def _search(self, name: str, team: str, position: str) -> tuple[dict | None, str]:
        full = name_key(name)
        cands: list[dict] = []
        # The search ranks fuzzily: a last name finds most players, a common one
        # (Smith) needs the full name.
        for q in (name.split()[-1], name):
            rows = self.client.get(SEARCH, culture="en-us", limit=50, q=q) or []
            cands = [r for r in rows if name_key(r.get("name", "")) == full
                     and _same_position(position, r.get("positionCode", ""))]
            if cands:
                break
        if len(cands) > 1:
            cands = [r for r in cands if team in (r.get("teamAbbrev"), r.get("lastTeamAbbrev"))] or cands
        if len({r["playerId"] for r in cands}) != 1:
            return None, "unmatched"
        pid = str(cands[0]["playerId"])
        info = self.client.get(f"{API}/player/{pid}/landing") or {}
        return {"nhl_id": pid, "birth_date": info.get("birthDate", ""),
                "position": info.get("position", cands[0].get("positionCode", "")),
                "team": info.get("currentTeamAbbrev") or cands[0].get("lastTeamAbbrev") or ""}, "search"


def sync_players(client: Client, injuries: list[dict], players: list[dict],
                 season_ids: list[str], today: date) -> list[dict]:
    """Add an NHL id and birth date for every player not matched yet."""
    known = {p["key"]: dict(p) for p in players}
    retry_before = (today - timedelta(days=RECHECK_DAYS)).isoformat()
    todo: dict[str, dict] = {}
    for inj in sorted(injuries, key=lambda i: i["last_seen"]):
        key = player_key(inj)
        p = known.get(key)
        if p is None or (not p["nhl_id"] and p["checked"] < retry_before):
            todo[key] = inj
    matcher = PlayerMatcher(client, season_ids)
    for key, inj in todo.items():
        teams = dict.fromkeys([inj.get("latest_team") or inj["team"], inj["team"]])
        hit, how = None, "unmatched"
        for team in teams:
            hit, how = matcher.match(inj["player"], team, inj["position"])
            if hit:
                break
        known[key] = {"key": key, "player": inj["player"], "team": inj.get("latest_team") or inj["team"],
                      "nhl_id": hit["nhl_id"] if hit else "",
                      "birth_date": hit.get("birth_date", "") if hit else "",
                      "nhl_position": hit.get("position", "") if hit else "",
                      "matched_by": how, "checked": today.isoformat()}
    return sorted(known.values(), key=lambda p: p["key"])


# ---------------------------------------------------------------- schedule

def _game_row(g: dict, day: str | None = None) -> dict:
    return {"game_id": str(g["id"]), "season": str(g["season"]), "game_type": str(g["gameType"]),
            "date": g.get("gameDate") or day or "", "away": g["awayTeam"]["abbrev"],
            "home": g["homeTeam"]["abbrev"], "state": g.get("gameState", "")}


def sync_games(client: Client, games: list[dict], season_ids: list[str], today: date) -> list[dict]:
    """Regular-season and playoff games for the tracked seasons, with current states."""
    by_id = {g["game_id"]: dict(g) for g in games}

    def upsert(g: dict, day: str | None = None) -> None:
        if str(g.get("gameType")) in COUNTED_TYPES:
            by_id[str(g["id"])] = _game_row(g, day)

    for sid in season_ids:
        if not any(g["season"] == sid for g in by_id.values()):
            for team in TEAMS:
                for g in (client.get(f"{API}/club-schedule-season/{team}/{sid}") or {}).get("games", []):
                    upsert(g)

    # Refresh from the oldest unfinished game in the past (at most 60 days back) to today;
    # this also picks up playoff games, which are only scheduled as series are set.
    today_s = today.isoformat()
    floor = (today - timedelta(days=60)).isoformat()
    unfinished = [g["date"] for g in by_id.values()
                  if g["state"] not in DONE_STATES and floor <= g["date"] <= today_s]
    d = date.fromisoformat(min(unfinished + [(today - timedelta(days=6)).isoformat()]))
    while d <= today:
        week = client.get(f"{API}/schedule/{d.isoformat()}") or {}
        for day in week.get("gameWeek", []):
            for g in day.get("games", []):
                upsert(g, day.get("date"))
        d += timedelta(days=7)
    return sorted(by_id.values(), key=lambda g: (g["date"], g["game_id"]))


def boxscore_appearances(client: Client, game: dict) -> list[dict]:
    """Everyone who dressed: skaters who played plus both dressed goalies."""
    b = client.get(f"{API}/gamecenter/{game['game_id']}/boxscore") or {}
    stats = b.get("playerByGameStats") or {}
    rows = []
    for side in ("awayTeam", "homeTeam"):
        team = (b.get(side) or {}).get("abbrev", "")
        for grp in ("forwards", "defense", "goalies"):
            for p in (stats.get(side) or {}).get(grp, []):
                rows.append({"game_id": game["game_id"], "date": game["date"], "team": team,
                             "nhl_id": str(p["playerId"])})
    return rows


def sync_appearances(client: Client, games: list[dict], appearances: list[dict],
                     since: str, today: date) -> list[dict]:
    """Box scores for finished games from ``since`` on that aren't stored yet."""
    have = {a["game_id"] for a in appearances}
    new = []
    for g in games:
        if (g["state"] in DONE_STATES and since <= g["date"] <= today.isoformat()
                and g["game_id"] not in have):
            new.extend(boxscore_appearances(client, g))
    return appearances + new
