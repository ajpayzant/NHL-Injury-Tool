# NHL Injury Database

A running history of every player on the [CBS Sports NHL injury report](https://www.cbssports.com/nhl/injuries/),
scraped twice a day by a GitHub Action and browsable in a Streamlit app.

- **Pipeline:** `scripts/update.py` scrapes the report, updates one row per injury in
  `data/injuries.csv`, logs changes to `data/events.csv` and the run to `data/runs.csv`,
  and saves the raw scrape under `data/snapshots/`. It then syncs NHL.com data into `data/nhl/`
  (player ids and birth dates, the schedule, and who dressed in each game) and fills in games
  missed, the return check and re-injury flags.
- **App:** `app/streamlit_app.py` has pages for Overview, Latest Injury News, Injury Search, Teams, Players,
  Injury Types, Seasons, Season Trends and Data & Downloads (CSV, Excel, or a live Google Sheets
  `IMPORTDATA` link).

## Run locally

```
pip install -r requirements.txt
run_app.bat                      # or: python -m streamlit run app/streamlit_app.py
python -m pytest                 # 37 tests
python scripts/update.py         # scrape now (--dry-run to preview, --force to skip the row-count guard)
python scripts/update.py --nhl-only   # refresh only the NHL.com data (--no-nhl skips it)
```

On Windows set `PYTHONUTF8=1` (`run_app.bat` does this).

## Deploy

1. Push this folder to GitHub (`ajpayzant/NHL-Injury-Tool`). If you move it to another repo,
   change `GITHUB_REPO` in `app/core.py` so the Sheets link points at the right file.
2. **Actions:** `.github/workflows/scrape.yml` runs at 04:15 and 16:15 UTC (12:15 AM / PM Eastern in summer, an hour earlier in winter).
   It needs *Settings → Actions → General → Workflow permissions → Read and write*. To run it by hand, use
   *Actions → Scrape CBS injury report → Run workflow* (tick `force` to skip the row-count guard).
3. **Streamlit Cloud:** New app → this repo, branch `main`, main file `app/streamlit_app.py`,
   Python 3.13. Each Action commit redeploys the app with the new data.

## How the data works

| Rule | Detail |
|---|---|
| One row per injury | Players are matched by CBS player ID, so a trade or a new diagnosis (Upper Body → Shoulder) updates the same row. `team` is the team when the injury happened; `latest_team` is the current one. |
| Returns | A player missing from **2** scrapes in a row is marked returned, dated to the first scrape they were missing from. |
| Reopening | A player who reappears within **3 days** with the same injury type or body region reopens the old row instead of starting a new one. |
| Safety guard | A scrape with fewer than half the previous run's rows (when that run had 20 or more) is refused, so a broken page can't mark everyone returned. |
| Games missed | Team regular-season and playoff games the player didn't dress for (NHL box scores), from the first report until his first game back, so a player CBS drops early keeps counting. Preseason games don't count. |
| Return check | *Played*, *Awaiting first game*, *Not played since* (off the report but hasn't dressed), *On report*, *Playing while listed*, or *No NHL match*. |
| Re-injury | A new head / neck, upper or lower body injury within **60 days** of returning from one in the same region (*Same injury* if the type matches too). |
| NHL matching | CBS name + team → NHL roster (full name, then nickname, then any team), then the NHL player search. Unmatched players are retried weekly. Cached in `data/nhl/players.csv`. |
| Seasons | Assigned by first-report date; the league year turns over on July 1. |
| History | Rows before Sept 25, 2026 come from the original Google Sheet (tracking began May 7, 2026). Split-by-trade rows were merged, and rows the sheet never closed got an estimated return (`return_is_estimated`). Injuries already on the report on May 7 have `start_is_lower_bound` set and are left out of days-out averages. |

To re-import the Sheet: `python scripts/import_sheet.py --overwrite`. This replaces all the data, so
run `scripts/update.py` right after it.
