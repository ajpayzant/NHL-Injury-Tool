"""Scrape the CBS NHL injury report and fold it into data/.

    python scripts/update.py              # live scrape (what the GitHub Action runs)
    python scripts/update.py --dry-run    # scrape and report, write nothing
    python scripts/update.py --html page.html --now 2026-09-24T16:00:00Z
    python scripts/update.py --nhl-only   # just refresh the NHL.com data (games missed etc.)

After the scrape, NHL.com data is synced (player ids, schedule, box scores) and the
games-missed, return-check and re-injury columns are recomputed. If NHL.com is down
the scrape is still saved and those columns keep their cached values.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nhl_injuries import enrich, nhl, store  # noqa: E402
from nhl_injuries.scrape import ScrapeError, scrape  # noqa: E402
from nhl_injuries.tracker import apply_report, et_date, parse_utc  # noqa: E402


def sync_nhl(injuries: list[dict], events: list[dict], today, offline: bool = False) -> list[dict]:
    """Refresh the data/nhl/ cache, then recompute the NHL-derived injury columns."""
    players, games, apps = store.read_players(), store.read_games(), store.read_appearances()
    if not offline:
        sids = sorted({nhl.season_id(i["season"]) for i in injuries})
        since = min((i["first_seen"] for i in injuries), default=today.isoformat())
        client = nhl.Client()
        try:
            players = nhl.sync_players(client, injuries, players, sids, today)
            games = nhl.sync_games(client, games, sids, today)
            apps = nhl.sync_appearances(client, games, apps, since, today)
        except nhl.NHLError as e:
            print(f"WARNING: NHL.com sync incomplete, using cached data ({e})", file=sys.stderr)
        store.write_players(players)
        store.write_games(games)
        store.write_appearances(apps, games)
    out = enrich.apply(injuries, players, games, apps, events, today)
    matched = sum(1 for p in players if p["nhl_id"])
    print(f"  NHL.com: {matched}/{len(players)} players matched, {len(games)} games, "
          f"{len({a['game_id'] for a in apps})} box scores")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", help="parse a saved page instead of fetching CBS")
    ap.add_argument("--now", help="override the run time (UTC, e.g. 2026-09-24T16:00:00Z)")
    ap.add_argument("--force", action="store_true", help="skip the row-count sanity check")
    ap.add_argument("--dry-run", action="store_true", help="don't write anything")
    ap.add_argument("--no-nhl", action="store_true", help="skip fetching NHL.com data (use the cache)")
    ap.add_argument("--nhl-only", action="store_true", help="don't scrape CBS; only refresh NHL.com data")
    args = ap.parse_args()

    now = parse_utc(args.now) if args.now else datetime.now(timezone.utc).replace(microsecond=0)
    if args.nhl_only:
        store.write_injuries(sync_nhl(store.read_injuries(), store.read_events(), et_date(now)))
        return 0
    html = Path(args.html).read_text(encoding="utf-8") if args.html else None

    try:
        report = scrape(et_date(now), html)
        result = apply_report(store.read_injuries(), store.read_runs(), report, now, force=args.force)
    except ScrapeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    r = result.run
    print(f"{r['run_at']}  scraped {r['rows']}  new {r['new']}  updated {r['updated']}  "
          f"closed {r['closed']}  reopened {r['reopened']}")
    for e in result.events:
        if e["event"] != "status_changed":
            print(f"  {e['event']:13} {e['team']:4} {e['player']:24} {e['detail']}")

    if args.dry_run:
        print("(dry run - nothing written)")
        return 0
    store.write_snapshot(report, r["run_at"])
    store.append_run(r)
    store.append_events(result.events)
    store.write_injuries(result.injuries)
    store.write_injuries(sync_nhl(result.injuries, store.read_events(), et_date(now), offline=args.no_nhl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
