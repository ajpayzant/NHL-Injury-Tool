"""Turn a sequence of injury-report scrapes into injury episodes.

An episode opens the first time a player appears on the report and stays open
while they keep appearing. Rules (each fixes a problem in the old Apps Script):

* Matching is on the CBS player id, falling back to the player's name for rows
  imported without one -- never on team, so a trade doesn't open a second row.
* A player missing from ``MISSES_TO_CLOSE`` consecutive successful scrapes is
  marked returned, dated to the first scrape they were missing from. One miss
  alone doesn't close anything, so a page that briefly drops a player is harmless.
* A player who reappears within ``REOPEN_DAYS`` of being closed, with the same
  injury (type or body region), reopens that episode instead of starting a new one.
* A run that returns far fewer rows than the last one is refused outright,
  because it would otherwise start closing injuries that are still real.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .reference import (ET, expected_return, injury_category, on_ir, season_of,
                        status_category)
from .scrape import ReportRow, ScrapeError

MISSES_TO_CLOSE = 2
REOPEN_DAYS = 3
MIN_ROWS_RATIO = 0.5   # refuse a scrape below half the previous run's row count ...
MIN_ROWS_FLOOR = 20    # ... once the previous run had at least this many rows

INJURY_COLUMNS = [
    "injury_id", "player_id", "player", "position", "team", "latest_team",
    "injury_type", "category", "status", "status_category", "on_ir", "expected_return",
    "first_seen", "last_seen", "last_seen_at", "source_updated", "return_date",
    "days_out", "season", "start_is_lower_bound", "return_is_estimated", "origin", "notes",
]
# Filled in by enrich.py from NHL.com data after each run; the tracker leaves them alone.
ENRICH_COLUMNS = ["nhl_id", "birth_date", "games_missed", "first_game_back", "return_check",
                  "reinjury_of", "reinjury_match", "days_since_prior"]
INJURY_COLUMNS += ENRICH_COLUMNS
RUN_COLUMNS = ["run_at", "run_date", "rows", "new", "updated", "closed", "reopened"]
EVENT_COLUMNS = ["at", "date", "injury_id", "player_id", "player", "team", "event", "detail"]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def make_id(key: str, first_seen: str, injury_type: str) -> str:
    return hashlib.md5(f"{key}|{first_seen}|{norm(injury_type)}".encode()).hexdigest()[:16]


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def et_date(dt: datetime) -> date:
    return dt.astimezone(ET).date()


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def finalize(inj: dict, today: date) -> dict:
    """Recompute the derived columns from the base ones so they can never drift."""
    inj["category"] = injury_category(inj["injury_type"])
    inj["status_category"] = status_category(inj["status"])
    inj["on_ir"] = on_ir(inj["status"])
    exp = expected_return(inj["status"], date.fromisoformat(inj["last_seen"]))
    inj["expected_return"] = exp.isoformat() if exp else ""
    inj["season"] = season_of(inj["first_seen"])
    inj["latest_team"] = inj.get("latest_team") or inj["team"]
    if inj["return_date"]:
        inj["days_out"] = (date.fromisoformat(inj["return_date"])
                           - date.fromisoformat(inj["first_seen"])).days
    else:
        inj["days_out"] = ""
    for col in INJURY_COLUMNS:
        inj.setdefault(col, "")
    return inj


@dataclass
class RunResult:
    injuries: list[dict]
    run: dict
    events: list[dict] = field(default_factory=list)


def check_report(report: list[ReportRow], runs: list[dict]) -> None:
    if not report:
        raise ScrapeError("Scrape returned no injury rows; CBS layout may have changed "
                          "or the request was blocked.")
    if runs:
        prev = int(runs[-1]["rows"])
        if prev >= MIN_ROWS_FLOOR and len(report) < prev * MIN_ROWS_RATIO:
            raise ScrapeError(f"Scrape returned {len(report)} rows against {prev} last run; "
                              "refusing to treat that many players as returned. "
                              "Re-run with --force if the drop is real.")


def apply_report(injuries: list[dict], runs: list[dict], report: list[ReportRow],
                 now: datetime, force: bool = False) -> RunResult:
    if not force:
        check_report(report, runs)

    run_at, today = iso_utc(now), et_date(now)
    today_s = today.isoformat()
    injuries = [dict(i) for i in injuries]
    events: list[dict] = []
    counts = {"new": 0, "updated": 0, "closed": 0, "reopened": 0}

    def event(inj: dict, kind: str, detail: str = "") -> None:
        events.append({"at": run_at, "date": today_s, "injury_id": inj["injury_id"],
                       "player_id": inj["player_id"], "player": inj["player"],
                       "team": inj.get("latest_team") or inj["team"],
                       "event": kind, "detail": detail})

    open_by_pid: dict[str, dict] = {}
    open_by_name: dict[str, list[dict]] = {}
    for inj in injuries:
        if inj["return_date"]:
            continue
        if inj["player_id"]:
            open_by_pid[inj["player_id"]] = inj
        open_by_name.setdefault(norm(inj["player"]), []).append(inj)

    def find_open(row: ReportRow) -> dict | None:
        if row.player_id and row.player_id in open_by_pid:
            return open_by_pid[row.player_id]
        # Legacy rows (imported from the sheet) have no id; match on name if unambiguous.
        cands = [i for i in open_by_name.get(norm(row.player), [])
                 if not i["player_id"] or i["player_id"] == row.player_id]
        return cands[0] if len(cands) == 1 else None

    def find_recent_closed(row: ReportRow) -> dict | None:
        cutoff = (today - timedelta(days=REOPEN_DAYS)).isoformat()
        cands = [i for i in injuries
                 if i["return_date"] and i["return_date"] >= cutoff
                 and ((row.player_id and i["player_id"] == row.player_id)
                      or (not i["player_id"] and norm(i["player"]) == norm(row.player)))
                 and (norm(i["injury_type"]) == norm(row.injury_type)
                      or injury_category(i["injury_type"]) == injury_category(row.injury_type))]
        return max(cands, key=lambda i: i["return_date"]) if cands else None

    matched: set[str] = set()
    for row in report:
        inj = find_open(row)
        if inj is None:
            inj = find_recent_closed(row)
            if inj is not None:
                event(inj, "reopened", f"was marked returned {inj['return_date']}")
                inj["return_date"] = ""
                inj["return_is_estimated"] = ""
                counts["reopened"] += 1
        if inj is not None:
            if inj["injury_id"] in matched:  # two report rows resolved to one episode
                continue
            if norm(inj["injury_type"]) != norm(row.injury_type):
                event(inj, "type_changed", f"{inj['injury_type']} -> {row.injury_type}")
            if inj["status"] != row.status:
                event(inj, "status_changed", f"{inj['status']} -> {row.status}")
            if (inj.get("latest_team") or inj["team"]) != row.team:
                event(inj, "team_changed", f"{inj.get('latest_team') or inj['team']} -> {row.team}")
            inj.update(player_id=inj["player_id"] or row.player_id, player=row.player,
                       position=row.position, latest_team=row.team,
                       injury_type=row.injury_type, status=row.status,
                       source_updated=row.source_updated or inj["source_updated"],
                       last_seen=today_s, last_seen_at=run_at)
            counts["updated"] += 1
        else:
            inj = {
                "injury_id": make_id(row.player_id or norm(row.player), today_s, row.injury_type),
                "player_id": row.player_id, "player": row.player, "position": row.position,
                "team": row.team, "latest_team": row.team, "injury_type": row.injury_type,
                "status": row.status, "first_seen": today_s, "last_seen": today_s,
                "last_seen_at": run_at, "source_updated": row.source_updated,
                "return_date": "", "start_is_lower_bound": False,
                "return_is_estimated": False, "origin": "cbs", "notes": "",
            }
            injuries.append(inj)
            event(inj, "opened", f"{row.injury_type} - {row.status}")
            counts["new"] += 1
        matched.add(inj["injury_id"])

    # Close episodes that have now been missing from enough consecutive scrapes.
    run_times = [r["run_at"] for r in runs] + [run_at]
    for inj in injuries:
        if inj["return_date"] or inj["injury_id"] in matched:
            continue
        missed = [t for t in run_times if t > inj["last_seen_at"]]
        if len(missed) >= MISSES_TO_CLOSE:
            inj["return_date"] = et_date(parse_utc(missed[0])).isoformat()
            inj["return_is_estimated"] = False
            event(inj, "closed", f"off the report since {inj['return_date']}")
            counts["closed"] += 1

    injuries = [finalize(i, today) for i in injuries]
    injuries.sort(key=lambda i: (i["latest_team"], i["player"]))
    injuries.sort(key=lambda i: i["first_seen"], reverse=True)
    run = {"run_at": run_at, "run_date": today_s, "rows": len(report), **counts}
    return RunResult(injuries=injuries, run=run, events=events)
