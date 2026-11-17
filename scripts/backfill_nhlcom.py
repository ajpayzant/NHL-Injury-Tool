"""Load past NHL.com Status Reports into data/news.csv.

    python scripts/backfill_nhlcom.py --since 2026-10-07

Tries the date-built slug for every day from --since to today (one request each,
about half a second apart; days without a report are a 404 and skipped), then
re-links all news to players and CBS injuries. Reports already stored are re-read
only if NHL.com has edited them since.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nhl_injuries import dfo, nhlcom, store  # noqa: E402
from nhl_injuries.dfo import _utc  # noqa: E402
from nhl_injuries.tracker import et_date  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", required=True, help="first report date to try (YYYY-MM-DD)")
    ap.add_argument("--pause", type=float, default=0.5, help="seconds between requests")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    stamp, today = now.strftime("%Y-%m-%dT%H:%M:%SZ"), et_date(now)
    client = nhlcom.Client(pause=args.pause)
    news, injuries = store.read_news(), store.read_injuries()
    have = {r["source_url"]: r["updated_at"] for r in news if nhlcom.is_nhlcom(r)}
    stories = []
    d = date.fromisoformat(args.since)
    while d <= today:
        slug = nhlcom.slug_for(d)
        try:
            story = client.story(slug)
        except dfo.NewsError as e:
            print(f"  {slug}: {e}", file=sys.stderr)
            story = None
        if story and have.get(nhlcom.article_url(slug)) != _utc(story["lastUpdatedDate"]):
            stories.append(story)
        print(f"  {d}: {'found' if story else 'no report'}")
        d += timedelta(days=1)
    news, new, edited = nhlcom.merge(news, stories, stamp, nhlcom.positions_from(news, injuries))
    news = dfo.refresh(news, injuries, store.read_players(), today)
    store.write_news(news)
    print(f"{len(stories)} reports read: {new} new items, {edited} re-read")
    return 0


if __name__ == "__main__":
    sys.exit(main())
