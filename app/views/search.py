"""The old sheet's dashboard: filter the whole database, see counts, export."""
import pandas as pd
import streamlit as st

from core import avg_days_out, avg_games_missed, display_table, download_buttons, load, seasons, team_label
from nhl_injuries.reference import CATEGORY_ORDER, POSITIONS

inj, _, _ = load()

st.title("Injury Search")
st.caption("Filter the full injury database. Leave a filter empty to include everything.")

with st.container(border=True):
    r1 = st.columns([2, 1.3, 1, 1.4])
    player_q = r1[0].text_input("Player", placeholder="Search a name…")
    season_f = r1[1].multiselect("Season", seasons(inj))
    pos_f = r1[2].multiselect("Position", POSITIONS)
    status_f = r1[3].segmented_control("Status", ["All", "Open", "Returned"], default="All")

    r2 = st.columns([2, 1.3, 2.4])
    team_f = r2[0].multiselect("Team", sorted(inj["latest_team"].unique()), format_func=team_label)
    region_f = r2[1].multiselect("Body region",
                                 [c for c in CATEGORY_ORDER if c in set(inj["category"].astype(str))])
    types = sorted(inj.loc[inj["category"].astype(str).isin(region_f) if region_f else slice(None),
                           "injury_type"].unique())
    type_f = r2[2].multiselect("Injury type", types)

    lo, hi = inj["first_seen"].min().date(), inj["first_seen"].max().date()
    r3 = st.columns([2, 1.3, 2.4])
    dates = r3[0].date_input("First reported between", (lo, hi), min_value=lo, max_value=hi)
    check_f = r3[1].multiselect("Return check", sorted(set(inj["return_check"]) - {""}),
                                help="Whether he has actually played since coming off the report "
                                     "(NHL box scores).")
    reinj_f = r3[2].checkbox("Re-injuries only")
    include_non = r3[2].checkbox("Include non-injuries (suspensions, personal, contract)", value=True)

f = inj
if player_q:
    f = f[f["player"].str.contains(player_q.strip(), case=False, regex=False)]
if season_f:
    f = f[f["season"].isin(season_f)]
if pos_f:
    f = f[f["position"].isin(pos_f)]
if team_f:
    f = f[f["latest_team"].isin(team_f) | f["team"].isin(team_f)]
if region_f:
    f = f[f["category"].astype(str).isin(region_f)]
if type_f:
    f = f[f["injury_type"].isin(type_f)]
if status_f == "Open":
    f = f[f["is_open"]]
elif status_f == "Returned":
    f = f[~f["is_open"]]
if isinstance(dates, tuple) and len(dates) == 2:
    f = f[f["first_seen"].between(pd.Timestamp(dates[0]), pd.Timestamp(dates[1]))]
if check_f:
    f = f[f["return_check"].isin(check_f)]
if reinj_f:
    f = f[f["is_reinjury"]]
if not include_non:
    f = f[f["is_injury"]]

avg, n = avg_days_out(f)
avg_g, n_g = avg_games_missed(f)
c = st.columns(6)
c[0].metric("Matching injuries", len(f), border=True)
c[1].metric("Open", int(f["is_open"].sum()), border=True)
c[2].metric("Returned", int((~f["is_open"]).sum()), border=True)
c[3].metric("Avg days out", f"{avg:.1f}" if avg is not None else "—", border=True,
            help=f"Returned injuries only (n={n}). Excludes injuries already on the report when "
                 "tracking began, whose true start date is unknown.")
c[4].metric("Avg games out", f"{avg_g:.1f}" if avg_g is not None else "—", border=True,
            help=f"Injuries where he has played again, so the count is final (n={n_g}).")
c[5].metric("Re-injuries", int(f["is_reinjury"].sum()), border=True)

if f.empty:
    st.info("No injuries match these filters.")
else:
    display_table(f, ["player", "position", "age", "latest_team", "injury_type", "category", "status",
                      "first_seen", "return_date", "duration", "games_missed", "return_check",
                      "reinjury_match", "season", "notes"],
                  height=560)
    download_buttons(f, "nhl_injuries_filtered", key="search")
