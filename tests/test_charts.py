import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import charts  # noqa: E402


def test_count_axis_has_whole_ticks_only():
    for top, ticks in [(1, [0, 1]), (3, [0, 1, 2, 3]), (14, [0, 2, 4, 6, 8, 10, 12, 14]),
                       (37, [0, 5, 10, 15, 20, 25, 30, 35, 40])]:
        x = charts.count_x("n:Q", top).to_dict()
        assert x["axis"]["values"] == ticks
        assert x["scale"]["domain"] == [0, ticks[-1]]


def test_legend_charts_get_room_for_the_legend():
    df = charts.with_category_order(pd.DataFrame(
        {"injury_type": ["Knee"], "category": ["Lower Body"], "injuries": [1]}))
    stacked = charts.stacked_hbar(df, "injury_type", "injuries", "category").to_dict()
    plain = charts.hbar(df, "injury_type", "injuries").to_dict()
    assert stacked["height"] - plain["height"] == charts.LEGEND_HEIGHT
