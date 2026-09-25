import pandas as pd
import streamlit as st

import charts
from core import avg_days_out, display_table, games_lost, download_buttons, load, seasons
from nhl_injuries.reference import TEAMS

inj, events, _ = load()

st.title("Teams")

opts = list(TEAMS)
c = st.columns([2, 1, 3])
team = c[0].selectbox("Team", opts, format_func=lambda t: TEAMS[t][0],
                      index=opts.index(st.query_params.get("team", "ANA"))
                      if st.query_params.get("team") in opts else 0)
st.query_params["team"] = team
season_opts = ["All seasons"] + seasons(inj)
season = c[1].selectbox("Season", season_opts, index=1 if len(season_opts) > 1 else 0)

name, conf, div = TEAMS[team]
logo = f"https://assets.nhle.com/logos/nhl/svg/{team}_light.svg"
st.markdown(
    f"<div style='display:flex;align-items:center;gap:14px;margin:.25rem 0 1rem'>"
    f"<img src='{logo}' width='56' alt=''/><div><div style='font-size:1.6rem;font-weight:600'>{name}</div>"
    f"<div style='color:#52514e'>{conf} Conference · {div} Division</div></div></div>",
    unsafe_allow_html=True)

scope = inj if season == "All seasons" else inj[inj["season"] == season]
# An injury belongs to a team if it was that team's when it happened or is now.
mine = scope[(scope["team"] == team) | (scope["latest_team"] == team)]
current = inj[inj["is_open"] & (inj["latest_team"] == team)]

avg, n = avg_days_out(mine)
k = st.columns(5)
k[0].metric("On the report now", len(current), border=True)
k[1].metric("Injuries" + ("" if season == "All seasons" else f" in {season}"), len(mine), border=True)
k[2].metric("Days lost (returned)", int(mine.loc[~mine["is_open"], "days_out"].sum()), border=True,
            help="Sum of days missed over returned injuries; open injuries are still counting.")
k[3].metric("Games lost", games_lost(mine), border=True,
            help="Player-games missed through injury so far, open injuries included (NHL box scores).")
k[4].metric("Avg days missed", f"{avg:.1f}" if avg is not None else "—", border=True,
            help=f"Returned injuries with a known start date (n={n}).")

st.subheader("Currently injured")
if current.empty:
    st.success(f"No {name} players are on the injury report.")
else:
    display_table(current.sort_values("first_seen"),
                  ["player", "position", "age", "injury_type", "status", "first_seen",
                   "expected_return", "duration", "games_missed", "on_ir", "reinjury_match"])

left, right = st.columns(2, gap="large")
with left:
    st.subheader("League comparison")
    lg = (scope.groupby("latest_team").size().reindex(list(TEAMS), fill_value=0)
          .rename("injuries").reset_index().rename(columns={"latest_team": "team"}))
    lg["name"] = lg["team"].map(lambda t: TEAMS[t][0])
    rank = int(lg["injuries"].rank(ascending=False, method="min")[lg["team"] == team].iloc[0])
    st.caption(f"{name} rank **{rank} of 32** for injuries "
               f"{'overall' if season == 'All seasons' else 'in ' + season} (1 = most).")
    st.altair_chart(charts.hbar(lg, "team", "injuries", x_title="Injuries", highlight=team,
                                tooltip=["name:N", "injuries:Q"]), width="stretch")
with right:
    st.subheader("Injuries by type")
    if mine.empty:
        st.info("No injuries in this period.")
    else:
        by_type = charts.with_category_order(
            mine.groupby(["injury_type", "category"], observed=True).size()
            .rename("injuries").reset_index())
        st.altair_chart(charts.stacked_hbar(by_type, "injury_type", "injuries", "category",
                                            x_title="Injuries"), width="stretch")
    if season == "All seasons" and mine["season"].nunique() > 1:
        st.subheader("By season")
        st.altair_chart(charts.hbar(mine.groupby("season").size().rename("injuries").reset_index(),
                                    "season", "injuries", sort="-y", x_title="Injuries"),
                        width="stretch")

st.subheader("Injury history")
if mine.empty:
    st.info("No injuries recorded for this team in this period.")
else:
    display_table(mine.sort_values("first_seen", ascending=False),
                  ["player", "position", "team", "latest_team", "injury_type", "status",
                   "first_seen", "return_date", "duration", "games_missed", "return_check",
                   "reinjury_match", "season"])
    download_buttons(mine, f"{team.lower()}_injuries", key="team")

moves = events[(events["event"] == "team_changed") & events["detail"].str.contains(team)]
if not moves.empty:
    with st.expander(f"Players who changed teams while injured ({len(moves)})"):
        st.dataframe(moves[["date", "player", "detail"]].rename(
            columns={"date": "Date", "player": "Player", "detail": "Move"}),
            hide_index=True, width="stretch",
            column_config={"Date": st.column_config.DateColumn(format="MMM D, YYYY")})
