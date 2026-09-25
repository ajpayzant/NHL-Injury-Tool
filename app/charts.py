"""Altair chart builders. Colours are the validated default palette from the
dataviz reference; body regions take categorical slots in fixed order so a
region keeps its colour on every page and under every filter."""
from __future__ import annotations

import altair as alt
import pandas as pd

from nhl_injuries.reference import CATEGORY_ORDER

SERIES_1 = "#2a78d6"
MUTED = "#c9c8c2"
INK_2 = "#52514e"
GRID = "#e8e7e3"

CATEGORY_COLORS = dict(zip(CATEGORY_ORDER, [
    "#2a78d6",  # Head / Neck   slot 1 blue
    "#eb6834",  # Upper Body    slot 2 orange
    "#1baf7a",  # Lower Body    slot 3 aqua
    "#eda100",  # Illness       slot 4 yellow
    "#e87ba4",  # Undisclosed   slot 5 magenta
    "#008300",  # Non-injury    slot 6 green
    "#8a8984",  # Other         neutral
]))


# Nominal axes list every category; never let Vega thin the labels out.
Y_AXIS = alt.Axis(labelOverlap=False, labelLimit=200, grid=False, ticks=False)


# Streamlit fits the whole chart (axis and legend included) into this height,
# so charts with a legend need the extra room or the plot area collapses.
LEGEND_HEIGHT = 56


def bar_height(n: int, legend: bool = False) -> int:
    return 60 + 26 * max(n, 2) + (LEGEND_HEIGHT if legend else 0)


def count_x(field: str, top, title: str = "") -> alt.X:
    """Quantitative count axis with whole-number ticks only. Vega's default
    ticks on a small domain are fractional, and format "d" then prints 0 1 1."""
    top = max(int(top or 0), 1)
    step = next(s for s in (1, 2, 5, 10, 20, 25, 50, 100, 250, 500) if top / s <= 8)
    end = -(-top // step) * step
    return alt.X(field, title=title or None, scale=alt.Scale(domain=[0, end], nice=False),
                 axis=alt.Axis(values=list(range(0, end + 1, step)), format="d"))


def category_scale(present) -> alt.Scale:
    cats = [c for c in CATEGORY_ORDER if c in set(present)]
    return alt.Scale(domain=cats, range=[CATEGORY_COLORS[c] for c in cats])


def _base(chart: alt.Chart, height: int) -> alt.Chart:
    return (chart.properties(height=height)
            .configure_axis(grid=True, gridColor=GRID, domainColor=GRID, tickColor=GRID,
                            labelColor=INK_2, titleColor=INK_2, labelFontSize=12,
                            titleFontSize=12, titleFontWeight="normal")
            .configure_view(strokeWidth=0)
            .configure_legend(labelColor=INK_2, titleColor=INK_2, orient="top",
                              labelFontSize=12, titleFontSize=12))


def hbar(df: pd.DataFrame, y: str, x: str, *, y_title: str = "", x_title: str = "",
         highlight: str | None = None, tooltip=None, sort="-x", height: int | None = None,
         color: str = SERIES_1) -> alt.Chart:
    """Horizontal bars for a nominal category. One series -> one colour; with
    ``highlight`` the chosen bar keeps the colour and the rest go muted."""
    enc_color = (alt.condition(alt.datum[y] == highlight, alt.value(color), alt.value(MUTED))
                 if highlight is not None else alt.value(color))
    chart = alt.Chart(df).mark_bar(cornerRadiusEnd=4, height={"band": 0.72}).encode(
        y=alt.Y(f"{y}:N", sort=sort, title=y_title or None, axis=Y_AXIS),
        x=count_x(f"{x}:Q", df[x].max() if len(df) else 0, x_title),
        color=enc_color,
        tooltip=tooltip or [alt.Tooltip(f"{y}:N", title=y_title or y), alt.Tooltip(f"{x}:Q", title=x_title or x)],
    )
    return _base(chart, height or bar_height(len(df)))


def stacked_hbar(df: pd.DataFrame, y: str, x: str, stack: str, *, y_title: str = "",
                 x_title: str = "", height: int | None = None, sort=None) -> alt.Chart:
    """Horizontal bars stacked by body region, 2px surface gap between segments."""
    chart = alt.Chart(df).mark_bar(stroke="white", strokeWidth=2, height={"band": 0.72}).encode(
        y=alt.Y(f"{y}:N", sort=sort or "-x", title=y_title or None, axis=Y_AXIS),
        x=count_x(f"sum({x}):Q", df.groupby(y)[x].sum().max() if len(df) else 0, x_title),
        color=alt.Color(f"{stack}:N", scale=category_scale(df[stack]), title="Body region",
                        sort=CATEGORY_ORDER),
        order=alt.Order(f"{stack}_order:Q"),
        tooltip=[alt.Tooltip(f"{y}:N", title=y_title or y), alt.Tooltip(f"{stack}:N", title="Body region"),
                 alt.Tooltip(f"{x}:Q", title=x_title or x)],
    )
    return _base(chart, height or bar_height(df[y].nunique(), legend=True))


def with_category_order(df: pd.DataFrame, col: str = "category") -> pd.DataFrame:
    df = df.copy()
    df[col] = df[col].astype(str)
    df[f"{col}_order"] = df[col].map({c: i for i, c in enumerate(CATEGORY_ORDER)})
    return df


def monthly_bars(df: pd.DataFrame, month: str, count: str, *, color_by: str | None = None,
                 height: int = 260) -> alt.Chart:
    """Injuries first reported per month (vertical bars, optionally stacked by region)."""
    enc = dict(
        x=alt.X(f"yearmonth({month}):O", title=None, axis=alt.Axis(format="%b %Y", labelAngle=0)),
        y=alt.Y(f"sum({count}):Q", title="Injuries reported", axis=alt.Axis(tickMinStep=1, format="d")),
        tooltip=[alt.Tooltip(f"yearmonth({month}):T", title="Month", format="%B %Y"),
                 alt.Tooltip(f"sum({count}):Q", title="Injuries")],
    )
    if color_by:
        enc["color"] = alt.Color(f"{color_by}:N", scale=category_scale(df[color_by]),
                                 title="Body region", sort=CATEGORY_ORDER)
        enc["order"] = alt.Order(f"{color_by}_order:Q")
        enc["tooltip"] = enc["tooltip"][:1] + [alt.Tooltip(f"{color_by}:N", title="Body region"),
                                               alt.Tooltip(f"{count}:Q", title="Injuries")]
        mark = alt.Chart(df).mark_bar(stroke="white", strokeWidth=2)
    else:
        mark = alt.Chart(df).mark_bar(cornerRadiusEnd=4, color=SERIES_1)
    return _base(mark.encode(**enc), height)


def season_colors(seasons: list[str]) -> alt.Scale:
    """Newest season in the series colour, last season dark grey, older ones light grey,
    so the current season always reads first however many seasons are shown."""
    order = sorted(seasons, reverse=True)
    shades = [SERIES_1, INK_2] + [MUTED] * max(len(order) - 2, 0)
    return alt.Scale(domain=order, range=shades[:len(order)])


def season_lines(df: pd.DataFrame, y: str, *, y_title: str, height: int = 280) -> alt.Chart:
    """One line per season on a shared July-to-June axis. ``df`` has ``season``,
    ``axis_date`` (the date moved into a common reference year), ``date`` and ``y``."""
    top = df[y].max() if len(df) else 0
    step = next(s for s in (1, 2, 5, 10, 20, 25, 50, 100, 250, 500) if max(top, 1) / s <= 6)
    end = max(-(-int(top) // step) * step, step)
    base = alt.Chart(df).encode(
        x=alt.X("axis_date:T", title=None, axis=alt.Axis(format="%b", tickCount="month", labelOverlap=True),
                scale=alt.Scale(domain=["2000-07-01", "2001-06-30"])),
        y=alt.Y(f"{y}:Q", title=y_title, scale=alt.Scale(domain=[0, end], nice=False),
                axis=alt.Axis(values=list(range(0, end + 1, step)), format="d")),
        color=alt.Color("season:N", scale=season_colors(list(df["season"].unique())), title="Season",
                        sort="descending"),
    )
    hover = alt.selection_point(fields=["axis_date"], nearest=True, on="pointerover", empty=False)
    lines = base.mark_line(strokeWidth=2, interpolate="step-after")
    points = base.mark_point(filled=True, size=60, stroke="white", strokeWidth=2).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("season:N", title="Season"), alt.Tooltip("date:T", title="Date", format="%b %d, %Y"),
                 alt.Tooltip(f"{y}:Q", title=y_title)]).add_params(hover)
    rule = alt.Chart(df).mark_rule(color=GRID).encode(x="axis_date:T").transform_filter(hover)
    return _base(alt.layer(lines, rule, points), height + LEGEND_HEIGHT)


def share_bars(df: pd.DataFrame, y: str, stack: str, count: str, *, height: int | None = None) -> alt.Chart:
    """100% stacked horizontal bars: body-region mix per ``y``."""
    chart = alt.Chart(df).mark_bar(stroke="white", strokeWidth=2, height={"band": 0.72}).encode(
        y=alt.Y(f"{y}:N", sort="descending", title=None, axis=Y_AXIS),
        x=alt.X(f"sum({count}):Q", stack="normalize", title=None,
                axis=alt.Axis(format="%", values=[0, 0.25, 0.5, 0.75, 1])),
        color=alt.Color(f"{stack}:N", scale=category_scale(df[stack]), title="Body region", sort=CATEGORY_ORDER,
                        legend=alt.Legend(columns=4)),
        order=alt.Order(f"{stack}_order:Q"),
        tooltip=[alt.Tooltip(f"{y}:N"), alt.Tooltip(f"{stack}:N", title="Body region"),
                 alt.Tooltip(f"{count}:Q", title="Injuries")],
    )
    return _base(chart, height or bar_height(df[y].nunique(), legend=True) + 20)


def _day_axis(lo: pd.Timestamp, hi: pd.Timestamp, title: str, field: str) -> dict:
    """Day-level ticks (never hours) for a short date range."""
    step = max(1, -(-(hi - lo).days // 6))
    return dict(field=field, type="temporal", title=title,
                axis=alt.Axis(format="%b %d", tickCount={"interval": "day", "step": step}, labelOverlap=True),
                scale=alt.Scale(domain=[(lo - pd.Timedelta(days=1)).isoformat(),
                                        (hi + pd.Timedelta(days=1)).isoformat()]))


def return_history(h: pd.DataFrame, returned=None, played=None, end=None, height: int = 240) -> alt.Chart:
    """Expected return date (y) as it was reported on each date (x), as a step line
    carried forward to ``end`` (the return, or today while still out). Rules mark when
    he came off the report and when he first played."""
    h = h.copy()
    h["expected_label"] = h["expected_return"].dt.strftime("%b %d, %Y")
    points = h[["date", "expected_return", "status", "change", "expected_label"]]
    end = returned if returned is not None and pd.notna(returned) else end
    if end is not None and end > h["date"].max():
        points = pd.concat([points, points.iloc[[-1]].assign(date=end)], ignore_index=True)
    marks = [(returned, "Off report"), (played, "First game back")]
    marks = [(d, w) for d, w in marks if d is not None and pd.notna(d)]
    x_hi = max([points["date"].max()] + [d for d, _ in marks])
    y = alt.Y(**_day_axis(h["expected_return"].min(), h["expected_return"].max(), "Expected back",
                          "expected_return"))
    x = alt.X(**_day_axis(points["date"].min(), x_hi, "Reported on", "date"))
    line = alt.Chart(points).mark_line(interpolate="step-after", strokeWidth=2, color=SERIES_1).encode(x=x, y=y)
    dots = alt.Chart(h).mark_point(filled=True, size=70, color=SERIES_1, stroke="white", strokeWidth=2).encode(
        x=x, y=y,
        tooltip=[alt.Tooltip("date:T", title="Reported", format="%b %d, %Y"),
                 alt.Tooltip("status:N", title="Status"),
                 alt.Tooltip("expected_label:N", title="Expected back"),
                 alt.Tooltip("change:N", title="Change")])
    layers = [line, dots]
    rules = pd.DataFrame([{"date": d, "what": w} for d, w in marks])
    if len(rules):
        layers.append(alt.Chart(rules).mark_rule(color=INK_2, strokeDash=[4, 3]).encode(
            x="date:T", tooltip=[alt.Tooltip("what:N", title=""),
                                 alt.Tooltip("date:T", title="Date", format="%b %d, %Y")]))
        layers.append(alt.Chart(rules).mark_text(align="left", dx=4, dy=-4, baseline="top", color=INK_2,
                                                 fontSize=11).encode(x="date:T", y=alt.value(0), text="what:N"))
    return _base(alt.layer(*layers), height)


def timeline(df: pd.DataFrame, height: int | None = None) -> alt.Chart:
    """One bar per injury episode from first report to return (or today), by region."""
    chart = alt.Chart(df).mark_bar(cornerRadius=4, height=14).encode(
        x=alt.X("first_seen:T", title=None,
                axis=alt.Axis(format="%b %Y", tickCount="month", labelOverlap=True)),
        x2="end:T",
        y=alt.Y("label:N", sort=alt.EncodingSortField("first_seen", order="descending"), title=None,
                axis=alt.Axis(labelLimit=260, labelOverlap=False, ticks=False, grid=False)),
        color=alt.Color("category:N", scale=category_scale(df["category"]), title="Body region",
                        sort=CATEGORY_ORDER),
        tooltip=[alt.Tooltip("injury_type:N", title="Injury"),
                 alt.Tooltip("latest_team:N", title="Team"),
                 alt.Tooltip("first_seen:T", title="First reported", format="%b %d, %Y"),
                 alt.Tooltip("end_label:N", title="Returned"),
                 alt.Tooltip("duration:Q", title="Days missed"),
                 alt.Tooltip("status:N", title="Latest status")],
    )
    return _base(chart, height or 60 + LEGEND_HEIGHT + 30 * max(len(df), 2))
