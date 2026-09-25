import pandas as pd
import streamlit as st

from core import (DOWNLOAD, RAW_CSV_URL, for_download, history, history_for_download, last_updated,
                  load, to_excel, tracking_changes_since)
from nhl_injuries.enrich import REINJURY_DAYS
from nhl_injuries.tracker import MISSES_TO_CLOSE, REOPEN_DAYS

inj, events, runs = load()

st.title("Data & Downloads")

st.subheader("Download the full database")
full = for_download(inj)
ev = events.assign(date=events["date"].dt.strftime("%Y-%m-%d"))
c = st.columns([1, 1, 3])
c[0].download_button("Injuries (CSV)", full.to_csv(index=False).encode("utf-8"),
                     "nhl_injuries.csv", "text/csv", icon=":material/download:")
c[1].download_button(
    "Everything (Excel)",
    to_excel({"Injuries": full, "Expected Return History": history_for_download(history(), inj),
              "Report Changes": ev,
              "Scrape Log": runs.assign(run_at=runs["run_at"].dt.strftime("%Y-%m-%d %H:%M UTC"))}),
    "nhl_injury_database.xlsx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/table_view:")
st.caption(f"{len(inj):,} injuries · {len(events):,} report changes · {len(runs):,} scrapes · "
           f"updated {last_updated(runs)}")

st.subheader("Live copy in Google Sheets")
st.markdown("Paste this into cell A1 of any Google Sheet. It pulls the latest data every time "
            "Sheets refreshes (about once an hour), with no script or login needed.")
st.code(f'=IMPORTDATA("{RAW_CSV_URL}")', language=None)

st.subheader("How the data is built")
st.markdown(f"""
- **Source.** The [CBS Sports NHL injury report](https://www.cbssports.com/nhl/injuries/), scraped
  around 12 AM and 12 PM Eastern every day by a scheduled GitHub Action. Each raw scrape is saved
  in `data/snapshots/`, so the whole history can be rebuilt from source.
- **One row per injury.** A row opens the first time a player appears on the report and stays open
  while they remain on it. Players are matched by their CBS player id, so a trade or a refined
  diagnosis (Upper Body → Shoulder) updates the same row rather than starting a new one.
- **Returns.** A player missing from {MISSES_TO_CLOSE} scrapes in a row is marked returned, dated
  to the first scrape they were missing from. If they reappear within {REOPEN_DAYS} days with the
  same injury, the row is reopened instead of duplicated.
- **Days missed** is return date minus first report date. Injuries already on the report when
  tracking began have an unknown true start, so they are excluded from averages.
- **Games missed and return check.** Every player is matched to his NHL.com id, and the NHL box
  score of every regular-season and playoff game is checked for who dressed. Games missed counts
  his team's games from the first report until he actually dressed again, so a player CBS drops
  from the report before he plays keeps counting. *Return Check* says whether he has played since
  coming off the report (a scratch, a demotion or retirement shows up as *Not played since*).
- **Re-injury.** A new injury to the same body region (head / neck, upper or lower body) within
  {REINJURY_DAYS} days of coming back from the previous one. *Same injury* when the injury type
  matches too.
- **Expected-return history.** Every status the report has given an injury, the return date it
  implied, and whether that date was pushed back or moved up. Change tracking starts {tracking_changes_since(events)};
  injuries from the imported Sheet start with the status they had then.
- **Imported history.** Rows from the original Google Sheet (May–Sept 2026) were merged where one
  injury had been split across two teams, and rows the sheet never closed were closed the day
  after they were last seen (flagged *Return Estimated*).
""")

with st.expander("Column definitions"):
    defs = {
        "Injury ID": "Stable identifier for the injury.",
        "CBS Player ID": "CBS Sports player id (blank for a few imported rows until the player reappears).",
        "Team When Injured": "Team the player was on when the injury was first reported.",
        "Latest Team": "Team the player was listed under most recently.",
        "Injury Type": "CBS's injury description, e.g. Knee, Upper Body.",
        "Body Region": "Injury type grouped into Head / Neck, Upper Body, Lower Body, Illness, "
                       "Undisclosed or Non-injury (suspension, personal, contract).",
        "Latest Status": "Most recent status text, e.g. 'Expected to be out until at least Oct 2'.",
        "Status Category": "Out, Day-to-day, Questionable, Probable, Out for season.",
        "Expected Return": "Date parsed from the latest status text, when it gives one.",
        "First Reported / Last On Report": "First and most recent days the player was on the report.",
        "Date of Return": "Day the player came off the report; blank while still injured.",
        "Days Missed": "Date of Return minus First Reported.",
        "Games Missed": "Team games (regular season and playoffs) he didn't dress for, from the "
                        "first report until his first game back.",
        "First Game Back": "Date of the first game he dressed for after the injury.",
        "Return Check": "Played, Awaiting first game, Not played since, On report, Playing while "
                        "listed, or No NHL match.",
        "Re-injury": f"Same injury / Same body region when it began within {REINJURY_DAYS} days "
                     "of returning from an earlier injury; Re-injury Of is that injury's ID.",
        "NHL Player ID / Birth Date": "From NHL.com.",
        "Season": "NHL season by first report date (turns over July 1).",
        "Start Is Lower Bound": "Already on the report when tracking began; true start is earlier.",
        "Return Estimated": "Return date inferred at import rather than observed.",
    }
    st.dataframe(pd.DataFrame(defs.items(), columns=["Column", "Meaning"]),
                 hide_index=True, width="stretch")

st.subheader("Scrape log")
if runs.empty:
    st.info("No scrapes recorded yet.")
else:
    log = runs.sort_values("run_at", ascending=False).head(30).copy()
    log["run_at"] = log["run_at"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d %I:%M %p")
    st.dataframe(log.rename(columns={"run_at": "Run (ET)", "run_date": "Date", "rows": "Rows",
                                     "new": "New", "updated": "Updated", "closed": "Returned",
                                     "reopened": "Reopened"}),
                 hide_index=True, width="stretch")
