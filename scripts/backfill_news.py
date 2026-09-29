"""Load older Daily Faceoff injury news into data/news.csv.

    python scripts/backfill_news.py --since 2025-07-01     # page back to a date
    python scripts/backfill_news.py --pages 40             # or a number of pages

Pages are fetched one per second, newest first (20 items each; the feed goes back
to 2011, about 2,150 pages). Items already stored are kept as they are apart from
edited text. Daily Faceoff only knows each player's *current* team, so backfilled
items are marked ``team_is_current``; the app uses the linked CBS injury's team
for those where it has one.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nhl_injuries import dfo, store  # noqa: E402
from nhl_injuries.tracker import et_date  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--since", help="stop once items are older than this date (YYYY-MM-DD)")
    g.add_argument("--pages", type=int, help="number of pages to fetch")
    ap.add_argument("--start-page", type=int, default=1, help="resume from this page")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between pages")
    args = ap.parse_args()

    client = dfo.Client(pause=args.pause)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    news = store.read_news()
    items: list[dict] = []
    page, last = args.start_page, None
    try:
        while True:
            got, last = client.page(page)
            items.extend(got)
            oldest = got[-1]["createdAt"][:10] if got else ""
            if page % 25 == 0:
                print(f"  page {page}/{last}  back to {oldest}", flush=True)
            if (not got or page >= last or (args.since and oldest < args.since)
                    or (args.pages and page - args.start_page + 1 >= args.pages)):
                break
            page += 1
    except dfo.NewsError as e:
        print(f"WARNING: stopped at page {page} ({e}); saving what was fetched. "
              f"Resume with --start-page {page}", file=sys.stderr)
    if args.since:
        items = [i for i in items if i["createdAt"][:10] >= args.since]

    news, new, edited = dfo.merge(news, items, stamp, backfill=True)
    news = dfo.refresh(news, store.read_injuries(), store.read_players(), et_date(now))
    store.write_news(news)
    print(f"Fetched pages {args.start_page}-{page}: {new} new, {edited} edited, {len(news)} stored "
          f"({news[-1]['date'] if news else '-'} to {news[0]['date'] if news else '-'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
