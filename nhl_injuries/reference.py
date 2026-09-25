"""Static reference data: teams, seasons, injury and status categories."""
from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# NHL abbreviation -> (full name, conference, division)
TEAMS = {
    "ANA": ("Anaheim Ducks", "Western", "Pacific"),
    "BOS": ("Boston Bruins", "Eastern", "Atlantic"),
    "BUF": ("Buffalo Sabres", "Eastern", "Atlantic"),
    "CGY": ("Calgary Flames", "Western", "Pacific"),
    "CAR": ("Carolina Hurricanes", "Eastern", "Metropolitan"),
    "CHI": ("Chicago Blackhawks", "Western", "Central"),
    "COL": ("Colorado Avalanche", "Western", "Central"),
    "CBJ": ("Columbus Blue Jackets", "Eastern", "Metropolitan"),
    "DAL": ("Dallas Stars", "Western", "Central"),
    "DET": ("Detroit Red Wings", "Eastern", "Atlantic"),
    "EDM": ("Edmonton Oilers", "Western", "Pacific"),
    "FLA": ("Florida Panthers", "Eastern", "Atlantic"),
    "LAK": ("Los Angeles Kings", "Western", "Pacific"),
    "MIN": ("Minnesota Wild", "Western", "Central"),
    "MTL": ("Montreal Canadiens", "Eastern", "Atlantic"),
    "NSH": ("Nashville Predators", "Western", "Central"),
    "NJD": ("New Jersey Devils", "Eastern", "Metropolitan"),
    "NYI": ("New York Islanders", "Eastern", "Metropolitan"),
    "NYR": ("New York Rangers", "Eastern", "Metropolitan"),
    "OTT": ("Ottawa Senators", "Eastern", "Atlantic"),
    "PHI": ("Philadelphia Flyers", "Eastern", "Metropolitan"),
    "PIT": ("Pittsburgh Penguins", "Eastern", "Metropolitan"),
    "SJS": ("San Jose Sharks", "Western", "Pacific"),
    "SEA": ("Seattle Kraken", "Western", "Pacific"),
    "STL": ("St. Louis Blues", "Western", "Central"),
    "TBL": ("Tampa Bay Lightning", "Eastern", "Atlantic"),
    "TOR": ("Toronto Maple Leafs", "Eastern", "Atlantic"),
    "UTA": ("Utah Mammoth", "Western", "Central"),
    "VAN": ("Vancouver Canucks", "Western", "Pacific"),
    "VGK": ("Vegas Golden Knights", "Western", "Pacific"),
    "WSH": ("Washington Capitals", "Eastern", "Metropolitan"),
    "WPG": ("Winnipeg Jets", "Western", "Central"),
}

# CBS uses its own codes in team URLs (/nhl/teams/NJ/...); map the ones that differ.
CBS_CODE_TO_NHL = {
    "CLB": "CBJ", "LA": "LAK", "MON": "MTL", "NJ": "NJD", "SJ": "SJS",
    "TB": "TBL", "LV": "VGK", "WAS": "WSH",
}

# CBS display names in the team headings, as a fallback when the URL code is unknown.
CBS_NAME_TO_NHL = {
    "Anaheim": "ANA", "Boston": "BOS", "Buffalo": "BUF", "Calgary": "CGY",
    "Carolina": "CAR", "Chicago": "CHI", "Colorado": "COL", "Columbus": "CBJ",
    "Dallas": "DAL", "Detroit": "DET", "Edmonton": "EDM", "Florida": "FLA",
    "Los Angeles": "LAK", "Minnesota": "MIN", "Montreal": "MTL", "Nashville": "NSH",
    "New Jersey": "NJD", "N.Y. Islanders": "NYI", "N.Y. Rangers": "NYR",
    "Ottawa": "OTT", "Philadelphia": "PHI", "Pittsburgh": "PIT", "San Jose": "SJS",
    "Seattle": "SEA", "St. Louis": "STL", "Tampa Bay": "TBL", "Toronto": "TOR",
    "Utah": "UTA", "Vancouver": "VAN", "Vegas": "VGK", "Washington": "WSH",
    "Winnipeg": "WPG",
}

POSITIONS = ["C", "LW", "RW", "D", "G"]
POSITION_GROUP = {"C": "Forward", "LW": "Forward", "RW": "Forward", "D": "Defense", "G": "Goalie"}

# Injury type -> body region. Anything unlisted falls to "Other".
INJURY_CATEGORY = {
    **dict.fromkeys(
        ["Head", "Concussion", "Neck", "Face", "Jaw", "Eye", "Ear", "Nose", "Dental", "Mouth"],
        "Head / Neck"),
    **dict.fromkeys(
        ["Upper Body", "Shoulder", "Arm", "Upper Arm", "Elbow", "Forearm", "Wrist", "Hand",
         "Finger", "Thumb", "Chest", "Pectoral", "Ribs", "Collarbone", "Clavicle", "Back",
         "Abdomen", "Oblique", "Bicep", "Tricep", "Sternum"],
        "Upper Body"),
    **dict.fromkeys(
        ["Lower Body", "Hip", "Groin", "Knee", "Kneecap", "Leg", "Lower Leg", "Upper Leg",
         "Ankle", "Foot", "Toe", "Heel", "Achilles", "Hamstring", "Quadriceps", "Quad",
         "Thigh", "Calf", "Shin", "Adductor", "Pelvis", "Tailbone"],
        "Lower Body"),
    **dict.fromkeys(["Illness", "Flu", "COVID-19"], "Illness"),
    "Undisclosed": "Undisclosed",
    **dict.fromkeys(
        ["Suspension", "Personal", "Contract Dispute", "Not Injury Related", "Rest",
         "Conditioning", "Visa", "Paternity", "Bereavement"],
        "Non-injury"),
}
CATEGORY_ORDER = ["Head / Neck", "Upper Body", "Lower Body", "Illness", "Undisclosed",
                  "Non-injury", "Other"]


def injury_category(injury_type: str) -> str:
    return INJURY_CATEGORY.get((injury_type or "").strip(), "Other")


def season_of(d: date | datetime | str) -> str:
    """NHL season label for a date. The league year turns over on July 1, so
    anything first seen from July onward counts toward the upcoming season."""
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
_EXPECTED_RE = re.compile(r"out until at least (\w{3})\w*\.? (\d{1,2})", re.I)


def status_category(status: str) -> str:
    s = (status or "").lower()
    # CBS writes "until at least Jul 1" (the league-year rollover) for season-ending injuries.
    if "out for the season" in s or "until at least jul 1" in s:
        return "Out for season"
    if "out until" in s or s.startswith("out") or " out" in s:
        return "Out"
    if "day-to-day" in s:
        return "Day-to-day"
    if "questionable" in s:
        return "Questionable"
    if "probable" in s:
        return "Probable"
    if "suspen" in s:
        return "Suspended"
    return "Other"


def on_ir(status: str) -> bool:
    return (status or "").strip().upper().startswith(("IR", "LTIR"))


def expected_return(status: str, as_of: date) -> date | None:
    """Parse 'Expected to be out until at least Oct 2' into a date. CBS omits the
    year, so pick the first such date that is not more than ~2 months in the past."""
    m = _EXPECTED_RE.search(status or "")
    if not m or m.group(1)[:3].title() not in _MONTHS:
        return None
    month, day = _MONTHS[m.group(1)[:3].title()], int(m.group(2))
    for year in (as_of.year, as_of.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if (d - as_of).days >= -60:
            return d
    return None
