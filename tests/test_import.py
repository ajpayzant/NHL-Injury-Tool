import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from import_sheet import close_stale, load_sheet, merge_team_changes, to_rows  # noqa: E402

XLSX = Path(__file__).parent / "fixtures" / "sheet_2026-09-24.xlsx"


def test_import_merges_team_changes_and_closes_stale_rows():
    rows = to_rows(load_sheet(str(XLSX)))
    assert len(rows) == 196
    merged, log = merge_team_changes(rows)
    assert len(merged) == 184 and len(log) == 12

    kyrou = [r for r in merged if r["player"] == "Jordan Kyrou"]
    assert len(kyrou) == 1
    assert (kyrou[0]["team"], kyrou[0]["latest_team"], kyrou[0]["first_seen"]) == ("STL", "WSH", "2026-05-07")

    # Separate episodes stay separate: Makar's May injury was closed before September's.
    assert len([r for r in merged if r["player"] == "Cale Makar"]) == 2

    closed = close_stale(merged)
    still_open = [r for r in merged if not r["return_date"]]
    assert closed == 105
    assert all(r["last_seen"] == "2026-09-24" for r in still_open)
    est = [r for r in merged if r["return_is_estimated"]]
    assert all(r["return_date"] > r["last_seen"] for r in est)
