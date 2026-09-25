"""Columns that need NHL.com data or more than one injury row.

* **Games missed / return check.** Team games (regular season and playoffs) the
  player didn't dress for, from the first report until he actually played again.
  Coming off the CBS report isn't proof of a return, so the first game he dressed
  for afterwards is looked up in the box scores:

  - ``On report``            still listed by CBS
  - ``Playing while listed`` still listed, but dressed for his team's latest game
  - ``Played``               off the report and has dressed for a game since
  - ``Awaiting first game``  off the report; his team hasn't played since
  - ``Not played since``     off the report, but has missed every game since
                             (scratched, sent down, retired, or CBS dropped him early)
  - ``No NHL match``         couldn't be matched to an NHL player id

* **Re-injury.** A new injury to the same body region within ``REINJURY_DAYS`` of
  coming back from the last one (injuries only; suspensions and illness excluded).

* **Expected-return history.** Each status the injury has had, with the return date
  it implied and how that moved.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date

from .nhl import player_key
from .reference import expected_return, injury_category, status_category
from .tracker import norm

REINJURY_DAYS = 60
REINJURY_REGIONS = ("Head / Neck", "Upper Body", "Lower Body")


# ---------------------------------------------------------------- games missed

def team_spans(inj: dict, events: list[dict]) -> list[tuple[str, str]]:
    """[(from_date, team)] for the injury, using its team_changed events."""
    moves = sorted((e["date"], e["detail"].split("->")[-1].strip()) for e in events
                   if e["injury_id"] == inj["injury_id"] and e["event"] == "team_changed")
    if not moves and inj.get("latest_team") and inj["latest_team"] != inj["team"]:
        # Rows merged at import don't record when the move happened; the new team is the
        # one whose games the player would have been dressing for since.
        return [("", inj["latest_team"])]
    return [("", inj["team"])] + moves


def team_on(spans: list[tuple[str, str]], day: str) -> str:
    return spans[bisect_right([s for s, _ in spans], day) - 1][1]


def games_missed(inj: dict, team_games: dict[str, list[tuple[str, str]]],
                 spans: list[tuple[str, str]], dressed: set[str],
                 played_dates: list[str]) -> dict:
    """``team_games``: team -> [(date, game_id)] finished games with box scores.
    ``dressed``: game ids the player dressed for. ``played_dates``: sorted dates
    of those games (any team)."""
    first, ret = inj["first_seen"], inj["return_date"]
    if not inj.get("nhl_id"):
        return {"games_missed": "", "first_game_back": "",
                "return_check": "On report" if not ret else "No NHL match"}

    games = sorted({g for t in {t for _, t in spans} for g in team_games.get(t, [])
                    if g[0] >= first and team_on(spans, g[0]) == t})
    window = [g for g in games if not ret or g[0] < ret]
    missed = [g for g in window if g[1] not in dressed]
    after = missed[-1][0] if missed else None
    back = next((d for d in played_dates if (d > after if after else d >= first)), None)

    if not ret:
        playing = bool(window) and window[-1][1] in dressed
        return {"games_missed": len(missed), "first_game_back": "",
                "return_check": "Playing while listed" if playing else "On report"}

    # Off the report: keep counting until he actually dresses again.
    later = [g for g in games if g[0] >= ret and (back is None or g[0] < back)
             and g[1] not in dressed]
    check = "Played" if back else ("Not played since" if later else "Awaiting first game")
    return {"games_missed": len(missed) + len(later), "first_game_back": back or "",
            "return_check": check}


def add_games_missed(injuries: list[dict], games: list[dict], appearances: list[dict],
                     events: list[dict], today: date) -> None:
    with_box = {a["game_id"] for a in appearances}
    team_games: dict[str, list[tuple[str, str]]] = {}
    for g in games:
        if g["game_id"] in with_box and g["date"] <= today.isoformat():
            for t in (g["home"], g["away"]):
                team_games.setdefault(t, []).append((g["date"], g["game_id"]))
    by_player: dict[str, list[tuple[str, str]]] = {}
    for a in appearances:
        by_player.setdefault(a["nhl_id"], []).append((a["date"], a["game_id"]))
    for inj in injuries:
        mine = sorted(by_player.get(inj.get("nhl_id") or "", []))
        inj.update(games_missed(inj, team_games, team_spans(inj, events),
                                {gid for _, gid in mine}, [d for d, _ in mine]))


# ---------------------------------------------------------------- re-injury

def person(inj: dict) -> str:
    return inj.get("nhl_id") or inj["player_id"] or "name:" + norm(inj["player"])


def add_reinjuries(injuries: list[dict]) -> None:
    by_person: dict[str, list[dict]] = {}
    for inj in injuries:
        inj.update(reinjury_of="", reinjury_match="", days_since_prior="")
        by_person.setdefault(person(inj), []).append(inj)
    for rows in by_person.values():
        for inj in rows:
            region = injury_category(inj["injury_type"])
            if region not in REINJURY_REGIONS:
                continue
            start = date.fromisoformat(inj["first_seen"])
            prior = [p for p in rows if p is not inj and p["return_date"]
                     and p["return_date"] <= inj["first_seen"]
                     and injury_category(p["injury_type"]) == region
                     and (start - date.fromisoformat(p["return_date"])).days <= REINJURY_DAYS]
            if prior:
                p = max(prior, key=lambda r: r["return_date"])
                inj.update(reinjury_of=p["injury_id"],
                           reinjury_match="Same injury" if norm(p["injury_type"]) == norm(inj["injury_type"])
                           else "Same body region",
                           days_since_prior=(start - date.fromisoformat(p["return_date"])).days)


# ---------------------------------------------------------------- players

def add_player_details(injuries: list[dict], players: list[dict]) -> None:
    by_key = {p["key"]: p for p in players}
    for inj in injuries:
        p = by_key.get(player_key(inj), {})
        inj["nhl_id"] = p.get("nhl_id", "")
        inj["birth_date"] = p.get("birth_date", "")


def apply(injuries: list[dict], players: list[dict], games: list[dict],
          appearances: list[dict], events: list[dict], today: date) -> list[dict]:
    injuries = [dict(i) for i in injuries]
    add_player_details(injuries, players)
    add_games_missed(injuries, games, appearances, events, today)
    add_reinjuries(injuries)
    return injuries


# ---------------------------------------------------------------- expected return

def _change(prev: dict | None, cur: dict) -> str:
    if prev is None:
        return "First report"
    if cur["status_category"] == "Out for season" and prev["status_category"] != "Out for season":
        return "Ruled out for season"
    if cur["on_ir"] and not prev["on_ir"]:
        return "Placed on IR"
    if prev["expected_return"] and cur["expected_return"]:
        days = (date.fromisoformat(cur["expected_return"]) - date.fromisoformat(prev["expected_return"])).days
        if days > 0:
            return f"Pushed back {days} day{'s' if days != 1 else ''}"
        if days < 0:
            return f"Moved up {-days} day{'s' if days != -1 else ''}"
    if cur["status_category"] != prev["status_category"]:
        return f"Now {cur['status_category'].lower()}"
    return "Status reworded"


def expected_return_history(injuries: list[dict], events: list[dict]) -> list[dict]:
    """One row per status an injury has had, oldest first, from the report-change log.
    Injuries imported from the old Sheet start from the status they had at import."""
    by_injury: dict[str, list[dict]] = {}
    for e in events:
        by_injury.setdefault(e["injury_id"], []).append(e)
    out = []
    for inj in injuries:
        evs = sorted(by_injury.get(inj["injury_id"], []), key=lambda e: e["at"])
        changes = [e for e in evs if e["event"] == "status_changed"]
        opened = next((e for e in evs if e["event"] == "opened"), None)
        if opened:
            steps = [(opened["date"], opened["detail"].split(" - ", 1)[-1], True)]
        elif changes:
            steps = [(inj["first_seen"], changes[0]["detail"].split(" -> ", 1)[0], False)]
        else:
            steps = [(inj["first_seen"], inj["status"], False)]
        steps += [(e["date"], e["detail"].split(" -> ", 1)[-1], True) for e in changes]
        prev = None
        for day, status, dated in steps:
            exp = expected_return(status, date.fromisoformat(day))
            cur = {"injury_id": inj["injury_id"], "date": day, "status": status,
                   "status_category": status_category(status),
                   "on_ir": status.strip().upper().startswith(("IR", "LTIR")),
                   "expected_return": exp.isoformat() if exp else "", "date_known": dated}
            cur["change"] = _change(prev, cur)
            out.append(cur)
            prev = cur
    return out
