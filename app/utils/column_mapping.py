"""
Complete mapping of 33 vehicle complaint issues to their Excel column ranges.
Column ranges correspond to the follow-up questions for each issue.
"""

# Excel column letter to index conversion helper
def col_letter_to_index(col: str) -> int:
    """Convert Excel column letter (A, B, ... Z, AA, AB...) to 0-based index."""
    result = 0
    for char in col.upper():
        result = result * 26 + (ord(char) - ord('A') + 1)
    return result - 1


def index_to_col_letter(index: int) -> str:
    """Convert 0-based column index to Excel column letter."""
    result = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


# ============================================================
# 33 ISSUES → COLUMN RANGE MAPPING (FIXED)
# ============================================================
ISSUE_COLUMN_RANGE_MAPPING = {
    # ── Unchanged (before FR) ─────────────────────────────────────
    "Brake issues":                {"start": "EP", "end": "EX", "count": 9},
    "Cable issues":                {"start": "EY", "end": "FD", "count": 6},
    "Chain issue":                 {"start": "FE", "end": "FE", "count": 1},
    "Chain case issue":            {"start": "FF", "end": "FF", "count": 1},
    "Clutch issues":               {"start": "FG", "end": "FK", "count": 5},

    # ── Electrical issues: FL to FY (was FL to FW, now +2 wider) ──
    "Electrical issues":           {"start": "FL", "end": "FY", "count": 14},

    # ── Everything from Engine onward shifts +2 ───────────────────
    "Engine issues":               {"start": "FZ", "end": "GG", "count": 8},
    "Gear issues":                 {"start": "GH", "end": "GO", "count": 9},
    "Handle Bar issues":           {"start": "GP", "end": "HQ", "count": 28},
    "Kicker issues":               {"start": "HR", "end": "HS", "count": 2},
    "Low Mileage":                 {"start": "HT", "end": "HX", "count": 5},
    "Low speed":                   {"start": "HY", "end": "HZ", "count": 2},
    "Muffler issues":              {"start": "IA", "end": "IE", "count": 5},
    "Starting trouble":            {"start": "IF", "end": "II", "count": 4},
    "Suspension issues":           {"start": "IJ", "end": "JD", "count": 21},
    "Vehicle noise":               {"start": "JE", "end": "JW", "count": 27},
    "Vibration":                   {"start": "JX", "end": "KN", "count": 31},
    "Mirror issues":               {"start": "KO", "end": "KS", "count": 5},
    "Wheel/Tyre issues":           {"start": "KT", "end": "MG", "count": 15},
    "Battery issues":              {"start": "MH", "end": "MK", "count": 4},
    "Jerking issues":              {"start": "ML", "end": "MO", "count": 4},
    "Part not available":          {"start": "MP", "end": "MQ", "count": 2},
    "Pick-up problem":             {"start": "MR", "end": "NB", "count": 11},
    "Running off":                 {"start": "NC", "end": "NI", "count": 7},
    "Throttle/Accelerator issue":  {"start": "NJ", "end": "NJ", "count": 1},
    "Vehicle body parts issue":    {"start": "NK", "end": "NW", "count": 13},
    "Fuel related issue":          {"start": "NX", "end": "NY", "count": 2},
    "Low Boot space":              {"start": "NZ", "end": "NZ", "count": 1},
    "Seat issue":                  {"start": "OA", "end": "OB", "count": 2},
    "Vehicle Pulling problem":     {"start": "OC", "end": "OD", "count": 2},
    "Roof top (soft top) issue":   {"start": "OE", "end": "OG", "count": 3},
    "Wiper problem":               {"start": "OH", "end": "OI", "count": 2},
    "Fastener issue":              {"start": "OJ", "end": "OJ", "count": 1},
}

# All 33 issues
ALL_ISSUES = list(ISSUE_COLUMN_RANGE_MAPPING.keys())

# Complaint section starts at column EL (index 137)
COMPLAINT_START_COL = "EL"
COMPLAINT_END_COL = "OD"
COMPLAINT_START_IDX = col_letter_to_index("EL")
COMPLAINT_END_IDX = col_letter_to_index("OD")

# ============================================================
# KEY COLUMN MAPPINGS (A-U essential columns)
# ============================================================
KEY_COLUMNS = {
    "A": "Timestamp",
    "B": "SURVEY DATE",
    "C": "SURVEYOR NAME",
    "D": "SURVEY LOCATION",
    "E": "BRAND & MODEL",
    "F": "VIN No.",
    "G": "CHASSIS No.",
    "H": "ODOMETER READING",
    "I": "PURCHASE DATE",
    "J": "DEALER NAME",
    "K": "USER NAME",
    "L": "USER AGE",
    "M": "USER PROFESSION",
    "N": "USER GENDER",
    "O": "USER MOBILE",
    "P": "USER EMAIL",
    "Q": "USER ADDRESS",
    "R": "PURPOSE",
    "S": "DAILY USAGE",
    "T": "FUEL TYPE",
    "U": "ENGINE CC",
}

# NPS column
NPS_COLUMN = "AA"

# Complaint group columns (L2) - DF to EI (DB-DE were rating columns: Best, Bad, Average)
COMPLAINT_GROUP_START = "DF"
COMPLAINT_GROUP_END = "EI"
COMPLAINT_GROUP_START_IDX = col_letter_to_index("DF")
COMPLAINT_GROUP_END_IDX = col_letter_to_index("EI")

TOTAL_EXPECTED_COLUMNS = 449

# Load 422 column headers from JSON
import json
from pathlib import Path

_HEADERS_FILE = Path(__file__).parent / "excel_column_headers.json"
COLUMN_HEADERS_MAP = {}
if _HEADERS_FILE.exists():
    try:
        with open(_HEADERS_FILE, "r", encoding="utf-8") as _f:
            COLUMN_HEADERS_MAP = json.load(_f)
    except Exception:
        COLUMN_HEADERS_MAP = {}


async def get_issue_column_range_mapping():
    """
    Fetch issue mappings from the IssueMapping collection.
    Returns a dict: {issue_name: {"start": col, "end": col, "count": count}}
    """
    from app.models.issue_mapping import IssueMapping
    
    mappings = await IssueMapping.find_all().to_list()
    if not mappings:
        # Fallback to hardcoded mapping if DB is empty
        return ISSUE_COLUMN_RANGE_MAPPING
    
    result = {}
    for mapping in mappings:
        issue_name = mapping.issue_name
        if mapping.column_range:
            result[issue_name] = {
                "start": mapping.column_range.start,
                "end": mapping.column_range.end,
                "count": mapping.column_range.count or 0,
            }
        else:
            result[issue_name] = {"start": "", "end": "", "count": 0}
    
    return result


def get_question_text_for_column(col_letter: str) -> str:
    """Return the actual question text for a column letter, or fallback to 'Column {col}'."""
    if not col_letter:
        return ""
    col_upper = col_letter.strip().upper()
    if col_upper in COLUMN_HEADERS_MAP and COLUMN_HEADERS_MAP[col_upper]:
        header = COLUMN_HEADERS_MAP[col_upper].strip()
        if header and not header.startswith("Unnamed:"):
            return header
    if col_upper in KEY_COLUMNS:
        return KEY_COLUMNS[col_upper]
    return f"Column {col_upper}"


def get_all_column_headers() -> dict:
    """Return a mapping of all 422 columns to their question texts."""
    result = {}
    for i in range(TOTAL_EXPECTED_COLUMNS):
        col = index_to_col_letter(i)
        result[col] = get_question_text_for_column(col)
    return result