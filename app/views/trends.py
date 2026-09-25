"""Season against season: how injuries build up through the year, and when they happen."""
import pandas as pd
import streamlit as st

import charts
from core import avg_days_out, fmt_date, games, games_lost, load, seasons, today
from nhl_injuries.nhl import season_id

inj, _, _ = load()
now = today()
sched = games()
tracking_start = inj["first_seen"].min()

st.title("Season Trends")
st.caption("Seasons lined up on the same calendar (July 1 to June 30) so the same point in "
           "each year can be compared.")

c = st.columns([3, 2])
all_seasons = seasons(inj)
picked = c[0].multiselect("Seasons", all_seasons, default=all_seasons)
injuries_only = c[1].toggle("Injuries only", value=True,
                            help="Leave out suspensions, personal leave and contract holdouts.")
if not picked:
    st.info("Pick at least one season.")
    st.stop()
data = inj[inj["is_injury"]] if injuries_only else inj


def season_start(label: str) -> pd.Timestamp:
    return pd.Timestamp(int(label[:4]), 7, 1)


def tracked_days(label: str) -> pd.DatetimeIndex:
    start = season_start(label)
    return pd.date_range(max(start, tracking_start), min(start + pd.Timedelta(days=364), now))


# ---------------------------------------------------------------- daily series
rows = []
for s in picked:
    start = season_start(s)
    mine = data[(data["season"] == s) & ~data["start_is_lower_bound"]]
    first = mine["first_seen"].sort_values().to_numpy()
    reinj = mine.loc[mine["is_reinjury"], "first_seen"].sort_values().to_numpy()
    for d in tracked_days(s):
        on_report = int(((data["first_seen"] <= d) & (data["return_date"].isna() | (data["return_date"] > d))).sum())
        rows.append({"season": s, "date": d, "axis_date": pd.Timestamp("2000-07-01") + (d - start),
                     "new": int((first <= d.to_datetime64()).sum()), "on_report": on_report,
                     "reinjuries": int((reinj <= d.to_datetime64()).sum())})
daily = pd.DataFrame(rows)

covered = {s: tracked_days(s) for s in picked}
if len(picked) > 1:
    days = [{(d - season_start(s)).days for d in covered[s]} for s in picked]
    if not set.intersection(*days):
        st.info(f"Tracking began {fmt_date(tracking_start)}, so the seasons shown don't share any "
                "dates yet. The lines will overlap from next July onward.", icon=":material/info:")

left, right = st.columns(2, gap="large")
with left:
    st.subheader("Injuries reported so far")
    st.altair_chart(charts.season_lines(daily, "new", y_title="Injuries reported"), width="stretch")
    st.caption("Running total of new injuries from July 1. Players already on the report when "
               "tracking began are left out, since their real start date is unknown.")
with right:
    st.subheader("Players on the report")
    st.altair_chart(charts.season_lines(daily, "on_report", y_title="On the report"), width="stretch")
    st.caption("Everyone listed on each date, including long-term injuries carried over from "
               "the previous season.")

# ---------------------------------------------------------------- same point
day_n = (now - season_start(all_seasons[0])).days
st.subheader(f"At the same point: {fmt_date(season_start(all_seasons[0]) + pd.Timedelta(days=day_n), year=False)}")
same = []
for s in picked:
    as_of = season_start(s) + pd.Timedelta(days=day_n)
    d = data[(data["season"] == s) & (data["first_seen"] <= as_of)]
    fresh = d[~d["start_is_lower_bound"]]
    avg, _ = avg_days_out(d[d["return_date"] <= as_of])
    on = data[(data["first_seen"] <= as_of) & (data["return_date"].isna() | (data["return_date"] > as_of))]
    tracked_from = max(season_start(s), tracking_start)
    seen = as_of >= tracked_from  # otherwise this point in that season predates tracking
    same.append({
        "Season": s, "As of": as_of, "Tracked from": tracked_from,
        "Injuries reported": len(fresh) if seen else None, "On the report": len(on) if seen else None,
        "Re-injuries": int(fresh["is_reinjury"].sum()) if seen else None,
        "Avg days missed": avg,
        "Most common": fresh["injury_type"].mode().iloc[0] if len(fresh) else None,
    })
same = pd.DataFrame(same)
st.dataframe(same, hide_index=True, width="stretch", placeholder="—", column_config={
    "As of": st.column_config.DateColumn(format="MMM D, YYYY"),
    "Tracked from": st.column_config.DateColumn(format="MMM D, YYYY"),
    "Avg days missed": st.column_config.NumberColumn(format="%.1f", help="Injuries returned by that date"),
})
if (same["Tracked from"] > same["As of"]).any():
    st.caption("Blank rows: that point in the season came before tracking began.")


# ---------------------------------------------------------------- phases
def phase_of(label: str):
    g = sched[sched["season"] == season_id(label)]
    reg = g.loc[g["game_type"] == "2", "date"]
    po = g.loc[g["game_type"] == "3", "date"]
    reg_start = reg.min() if len(reg) else pd.Timestamp(int(label[:4]), 10, 1)
    po_start = po.min() if len(po) else None
    po_end = po.max() if len(po) else None

    def phase(d: pd.Timestamp) -> tuple[int, str]:
        if d < reg_start:
            return 0, "Offseason & preseason"
        if po_start is None or d < po_start:
            return 1 + (d.year - reg_start.year) * 12 + d.month - reg_start.month, f"Regular season · {d:%b}"
        if d <= po_end:
            return 20, "Playoffs"
        return 21, "After playoffs"
    return phase, g


st.subheader("When injuries happen")
st.caption("Each season split into its phases. The rate per 100 team games evens out phases of "
           "different length; games lost counts the games missed by injuries that began in the phase.")
ph_rows = []
for s in picked:
    phase, g = phase_of(s)
    done = g[g["state"].isin(["OFF", "FINAL"]) & (g["date"] <= now)]
    mine = data[(data["season"] == s) & ~data["start_is_lower_bound"]]
    tracked = pd.Series([phase(d) for d in covered[s]], dtype=object)
    for (order, name), n_days in tracked.value_counts(sort=False).items():
        inj_ph = mine[[phase(d) == (order, name) for d in mine["first_seen"]]]
        team_games = 2 * sum(phase(d) == (order, name) for d in done["date"]
                             if max(season_start(s), tracking_start) <= d)
        ph_rows.append({
            "Season": s, "order": order, "Phase": name, "Days tracked": int(n_days),
            "Injuries": len(inj_ph), "Per week": len(inj_ph) / n_days * 7,
            "Team games": team_games or None,
            "Per 100 team games": len(inj_ph) / team_games * 100 if team_games else None,
            "Games lost": games_lost(inj_ph),
            "Avg days missed": avg_days_out(inj_ph)[0],
        })
phases = pd.DataFrame(ph_rows).sort_values(["Season", "order"], ascending=[False, True])
st.dataframe(phases.drop(columns="order"), hide_index=True, width="stretch", placeholder="—",
             column_config={
                 "Per week": st.column_config.NumberColumn(format="%.1f", help="Injuries reported per 7 days"),
                 "Per 100 team games": st.column_config.NumberColumn(format="%.1f"),
                 "Avg days missed": st.column_config.NumberColumn(format="%.1f"),
                 "Team games": st.column_config.NumberColumn(help="Finished NHL games in the phase × 2 teams"),
             })

# ---------------------------------------------------------------- mix
a, b = st.columns(2, gap="large")
with a:
    st.subheader("Body region mix")
    mix = charts.with_category_order(
        data[data["season"].isin(picked)].groupby(["season", "category"], observed=True).size()
        .rename("injuries").reset_index())
    st.altair_chart(charts.share_bars(mix, "season", "category", "injuries"), width="stretch")
with b:
    st.subheader("By position and age")
    sub = data[data["season"].isin(picked)]
    pos = (sub.groupby(["season", "position_group"]).size().unstack(fill_value=0))
    pos = pos.div(pos.sum(axis=1), axis=0) * 100
    ages = sub.groupby("season")["age_at_injury"].agg(["mean", "median"])
    out = pos.join(ages).reset_index().sort_values("season", ascending=False)
    cfg = {c: st.column_config.NumberColumn(format="%.0f%%") for c in pos.columns}
    cfg.update({"mean": st.column_config.NumberColumn("Avg age", format="%.1f"),
                "median": st.column_config.NumberColumn("Median age", format="%.0f"),
                "season": st.column_config.TextColumn("Season")})
    st.dataframe(out, hide_index=True, width="stretch", placeholder="—", column_config=cfg)
    st.caption("Share of each season's injuries by position group; age is the player's age "
               "when the injury was first reported.")
