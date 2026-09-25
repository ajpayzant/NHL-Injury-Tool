"""One-time import of the old Google Sheet's "Injury Log" tab into data/injuries.csv.

    python scripts/import_sheet.py                  # download the sheet and import
    python scripts/import_sheet.py --xlsx log.xlsx  # import a saved export

It repairs the two problems the Apps Script left in the log:

* Duplicate rows from team changes. The script matched on player + team, so a
  player who moved while injured got a second open row and the first never
  closed. Rows for the same player whose dates touch (the later one starts within
  MERGE_GAP_DAYS of the earlier one's last sighting, and the earlier one was never
  marked returned) are merged into one episode that keeps the original team.
* Stale open rows. Nothing ever filled Date of Return, so anyone who left the
  report stayed "open". Open rows not seen on the sheet's final scrape day are
  closed the day after they were last seen, flagged ``return_is_estimated``.
"""
from __future__ import annotations

import argparse
import io
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nhl_injuries import store  # noqa: E402
from nhl_injuries.reference import ET  # noqa: E402
from nhl_injuries.tracker import finalize, iso_utc, norm  # noqa: E402

SHEET_ID = "1NW0IFQVxxhdU_mKn-bXKKUQbDLDx070tRDYXkwdV9Kc"
EXPORT_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
MERGE_GAP_DAYS = 3


def _d(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT or v == "":
        return ""
    return pd.Timestamp(v).date().isoformat()


def _s(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def load_sheet(xlsx: str | None) -> pd.DataFrame:
    if xlsx:
        src = xlsx
    else:
        resp = requests.get(EXPORT_URL, timeout=60)
        resp.raise_for_status()
        src = io.BytesIO(resp.content)
    return pd.read_excel(src, sheet_name="Injury Log").dropna(how="all")


def to_rows(df: pd.DataFrame) -> list[dict]:
    first_scrape = min(_d(v) for v in df["Date Recorded"])
    rows = []
    for _, r in df.iterrows():
        first_seen, last_seen = _d(r["Date Recorded"]), _d(r["Last Seen On Report"]) or _d(r["Date Recorded"])
        rows.append({
            "injury_id": _s(r["Injury ID"]), "player_id": "", "player": _s(r["Player"]),
            "position": _s(r["Position"]), "team": _s(r["Team"]), "latest_team": _s(r["Team"]),
            "injury_type": _s(r["Injury Type"]), "status": _s(r["Injury Status"]),
            "first_seen": first_seen, "last_seen": last_seen,
            # The sheet only kept dates; call it noon Eastern on the last day seen.
            "last_seen_at": iso_utc(datetime.combine(date.fromisoformat(last_seen), time(12), ET)),
            "source_updated": _d(r["Source Updated Date"]), "return_date": _d(r["Date of Return"]),
            "start_is_lower_bound": first_seen == first_scrape,
            "return_is_estimated": False, "origin": "sheet", "notes": _s(r["Notes"]),
        })
    return rows


def merge_team_changes(rows: list[dict]) -> tuple[list[dict], list[str]]:
    by_player: dict[str, list[dict]] = {}
    for r in rows:
        by_player.setdefault(norm(r["player"]), []).append(r)

    out, log = [], []
    for eps in by_player.values():
        eps.sort(key=lambda r: (r["first_seen"], r["last_seen"]))
        cur = eps[0]
        for nxt in eps[1:]:
            gap_ok = (date.fromisoformat(nxt["first_seen"])
                      <= date.fromisoformat(cur["last_seen"]) + timedelta(days=MERGE_GAP_DAYS))
            if not cur["return_date"] and gap_ok:
                latest = nxt if nxt["last_seen"] >= cur["last_seen"] else cur
                log.append(f"{cur['player']}: {cur['team']} {cur['first_seen']}..{cur['last_seen']} "
                           f"+ {nxt['team']} {nxt['first_seen']}..{nxt['last_seen']}")
                note = f"Merged at import: listed under {cur['team']} then {nxt['team']}."
                cur = {**cur,
                       **{k: latest[k] for k in ("position", "latest_team", "injury_type", "status",
                                                 "last_seen", "last_seen_at", "source_updated",
                                                 "return_date")},
                       "notes": "; ".join(x for x in (cur["notes"], nxt["notes"], note) if x)}
            else:
                out.append(cur)
                cur = nxt
        out.append(cur)
    return out, log


def close_stale(rows: list[dict]) -> int:
    final_day = max(r["last_seen"] for r in rows)
    n = 0
    for r in rows:
        if not r["return_date"] and r["last_seen"] < final_day:
            r["return_date"] = (date.fromisoformat(r["last_seen"]) + timedelta(days=1)).isoformat()
            r["return_is_estimated"] = True
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xlsx", help="saved export of the sheet (default: download it)")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing data/injuries.csv")
    args = ap.parse_args()

    if store.INJURIES.exists() and not args.overwrite:
        print(f"{store.INJURIES} already exists; pass --overwrite to replace it.", file=sys.stderr)
        return 1

    rows = to_rows(load_sheet(args.xlsx))
    merged, log = merge_team_changes(rows)
    closed = close_stale(merged)
    today = datetime.now(ET).date()
    merged = [finalize(r, today) for r in merged]
    merged.sort(key=lambda i: (i["latest_team"], i["player"]))
    merged.sort(key=lambda i: i["first_seen"], reverse=True)
    store.write_injuries(merged)

    print(f"Imported {len(rows)} sheet rows -> {len(merged)} episodes "
          f"({len(log)} team-change merges, {closed} stale rows closed).")
    for line in log:
        print("  merged", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
