"""
Core Excel processing service.
Handles validation, extraction, chunking, and data storage.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import re

from app.utils.column_mapping import (
    # REMOVE: ISSUE_COLUMN_RANGE_MAPPING,
    KEY_COLUMNS,
    NPS_COLUMN,
    COMPLAINT_GROUP_START_IDX,
    COMPLAINT_GROUP_END_IDX,
    COMPLAINT_START_IDX,
    COMPLAINT_END_IDX,
    TOTAL_EXPECTED_COLUMNS,
    col_letter_to_index,
    index_to_col_letter,
    get_question_text_for_column,
    # ADD THIS:
    get_issue_column_range_mapping,  # new function
)

# ============================================================
# PASSIVE/GOOD FEEDBACK TOPIC MAPPING (columns AU to BM)
# ============================================================
PASSIVE_TOPIC_MAPPING = {
    "AU": "Brake",
    "AV": "Electrical",
    "AW": "Engine",
    "AX": "Load",
    "AY": "Maintenance",
    "AZ": "Mileage",
    "BA": "Mirror",
    "BB": "Vehicle",
    "BC": "Seat",
    "BD": "Sound",
    "BE": "Roof top (soft top)",
    "BF": "Spare parts",
    "BG": "Style",
    "BH": "Suspension",
    "BI": "Tyre",
    "BJ": "Vehicle price",
    "BK": "Income",
    "BL": "Windshield",
    "BM": "Brand image",
}

def validate_excel(file_path: str) -> Tuple[bool, str, Optional[pd.DataFrame]]:
    """
    Validate the uploaded Excel file.
    Returns: (is_valid, error_message, dataframe)
    """
    try:
        # Read full file directly - no column count validation
        df = pd.read_excel(file_path, header=0, engine="openpyxl")
        
        # Rename columns to letters: A, B, C, ... AA, AB, ...
        col_letters = [index_to_col_letter(i) for i in range(len(df.columns))]
        df.columns = col_letters
        
        return True, "", df
        
    except Exception as e:
        return False, f"Error reading Excel file: {str(e)}", None


def clean_value(val: Any) -> Any:
    """Convert pandas NaN/NaT to None and numpy types to Python natives."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, (pd.Timestamp, datetime)):
        return val.isoformat()
    return val


def safe_str(val: Any) -> str:
    """Return string value or 'Blank' for empty."""
    cleaned = clean_value(val)
    if cleaned is None or str(cleaned).strip() in ("", "nan", "NaT", "None"):
        return "Blank"
    return str(cleaned).strip()


def parse_date(val: Any) -> Optional[datetime]:
    """Safely parse a date value."""
    if val is None or pd.isna(val):
        return None
    try:
        if isinstance(val, (datetime, pd.Timestamp)):
            dt = pd.Timestamp(val).to_pydatetime()
            if pd.isna(dt) or str(dt) == "NaT":
                return None
            return dt
        if val and str(val).strip() not in ("", "nan", "NaT", "None"):
            dt = pd.to_datetime(val).to_pydatetime()
            if pd.isna(dt) or str(dt) == "NaT":
                return None
            return dt
    except Exception:
        pass
    return None


def parse_number(val: Any) -> Optional[float]:
    """Safely parse a numeric value."""
    try:
        cleaned = clean_value(val)
        if cleaned is not None:
            return float(cleaned)
    except (ValueError, TypeError):
        pass
    return None


def is_junk_value(val: str) -> bool:
    """
    Detect junk / placeholder values that should be excluded from analysis.
    Examples: "Submit Form....", "-----", "....", "12", "AB", etc.
    """
    patterns = [
        r"^Submit\s?Form",
        r"^Submit$",
        r"^\.+$",
        r"^[-_]+$",
        r"^[A-Za-z]{1,2}$",
        r"^[0-9]+$",
        r"^[A-Z]{1,3}\.?$",
        r"^\s*$",
    ]
    return any(re.match(p, val.strip(), re.IGNORECASE) for p in patterns)


async def extract_row_data(row: pd.Series, col_letters: List[str]) -> Dict[str, Any]:
    """
    Extract a single row into:
    - key_fields: indexed fields for fast filtering
    - full_data: all 422 columns
    - complaint_data: EL-OD columns grouped by issue
    - complaint_groups: list of issue names from DB to EI (multiple columns)
    """
    full_data = {}
    for col in col_letters:
        full_data[col] = clean_value(row.get(col))

    # Key fields
    key_fields = {
        "survey_date": parse_date(row.get("B")),
        "survey_location": safe_str(row.get("D")) if row.get("D") is not None else None,
        "brand_model": safe_str(row.get("E")) if row.get("E") is not None else None,
        "vin_number": safe_str(row.get("F")) if row.get("F") is not None else None,
        "odometer_reading": parse_number(row.get("H")),
        "user_name": safe_str(row.get("K")) if row.get("K") is not None else None,
        "user_age": parse_number(row.get("L")),
        "user_age_group": safe_str(row.get("M")) if row.get("M") is not None else None,
        "user_profession": safe_str(row.get("N")) if row.get("N") is not None else None,
        "mode_of_purchase": safe_str(row.get("I")) if row.get("I") is not None else None,
        "ownership": safe_str(row.get("Q")) if row.get("Q") is not None else None,
        "nps_score": parse_number(row.get(NPS_COLUMN)),
    }

    # ============================================================
    # NEW: Complaint groups extracted from DB to EI
    # Each column in this range contains a different issue
    # ============================================================
    complaint_groups = []
    for i in range(COMPLAINT_GROUP_START_IDX, COMPLAINT_GROUP_END_IDX + 1):
        if i < len(col_letters):
            col = col_letters[i]
            val = safe_str(row.get(col, ""))
            # Exclude blank and junk values (SubmitForm..., dots, dashes, numbers, etc.)
            if val and val != "Blank" and not is_junk_value(val):
                complaint_groups.append(val)

    # Remove duplicates (in case same issue appears in multiple columns)
    complaint_groups = list(set(complaint_groups))

    # ============================================================
    # Complaint data (EL to OD) - grouped by issue from DB
    # ============================================================
    issue_mapping = await get_issue_column_range_mapping()  # from DB
    complaint_data = {}
    for issue_name, range_info in issue_mapping.items():
        start_idx = col_letter_to_index(range_info["start"])
        end_idx = col_letter_to_index(range_info["end"])
        issue_key = issue_name.lower().replace(" ", "_").replace("/", "_")
        complaint_data[issue_key] = {}
        for i in range(start_idx, end_idx + 1):
            if i < len(col_letters):
                col = col_letters[i]
                complaint_data[issue_key][col] = safe_str(row.get(col, ""))

    # ============================================================
    # Passive/Good feedback (AU to BM) - grouped by topic
    # ============================================================
    passive_data = {}
    for col, topic in PASSIVE_TOPIC_MAPPING.items():
        val = safe_str(row.get(col, ""))
        # Exclude blank and junk values (SubmitForm..., dots, dashes, numbers, etc.)
        if val and val != "Blank" and not is_junk_value(val):
            passive_data.setdefault(topic, []).append(val)

    return {
        "key_fields": key_fields,
        "full_data": full_data,
        "complaint_data": complaint_data,
        "complaint_groups": complaint_groups,  # Now from DB to EI
        "passive_data": passive_data,
    }

async def compute_issue_analysis(
    responses: List[Dict[str, Any]], col_letters: List[str]
) -> List[Dict[str, Any]]:
    """
    Compute per-issue, per-follow-up answer counts from a list of response dicts.
    Returns list of issue summary dicts for IssueAnalysis model.
    """
    from collections import Counter, defaultdict

    issue_mapping = await get_issue_column_range_mapping()

    issue_summaries = []
    total_issue_count = sum(len(r.get("complaint_groups", [])) for r in responses)

    for issue_name, range_info in issue_mapping.items():
        start_idx = col_letter_to_index(range_info["start"])
        end_idx = col_letter_to_index(range_info["end"])

        issue_records = [r for r in responses if issue_name in r.get("complaint_groups", [])]
        total_complaints = len(issue_records)
        percentage = (total_complaints / len(responses) * 100) if responses else 0

        # ============================================================
        # Parse columns into sub-issue groups and sub-columns
        # ============================================================
        sub_issue_groups = defaultdict(lambda: {
            "name": "",
            "total": 0,
            "columns": [],
            "sub_columns": defaultdict(lambda: {
                "column_letter": "",
                "question_text": "",
                "total": 0,
                "answers": Counter(),
            })
        })

        for col_idx in range(start_idx, end_idx + 1):
            if col_idx >= len(col_letters):
                break
            col = col_letters[col_idx]
            question_text = get_question_text_for_column(col)
            
            # Parse "Handle bar bend [Yes-Is vehicle fall down?]" 
            # into ("Handle bar bend", "Yes-Is vehicle fall down?")
            sub_issue_name, sub_column_name = parse_column_name(question_text)
            
            # Collect answers for this column
            answers = []
            for r in responses:
                val = safe_str(r.get("full_data", {}).get(col, ""))
                answers.append(val if val else "Blank")
            
            answer_counts = Counter(answers)
            total_for_col = sum(answer_counts.values())
            
            # Add to group
            group = sub_issue_groups[sub_issue_name]
            group["name"] = sub_issue_name
            group["total"] += total_for_col
            group["columns"].append(col)
            
            sub_col = group["sub_columns"][sub_column_name]
            sub_col["column_letter"] = col
            sub_col["question_text"] = sub_column_name
            sub_col["total"] += total_for_col
            sub_col["answers"].update(answer_counts)

        # Convert to output format
        sub_issues_out = []
        for sub_issue_name, group in sub_issue_groups.items():
            sub_columns_out = []
            for sub_col_name, sub_col in group["sub_columns"].items():
                total_answers = sum(sub_col["answers"].values())
                answer_list = [
                    {
                        "value": v,
                        "count": c,
                        "percentage": round(c / total_answers * 100, 2) if total_answers else 0.0,
                    }
                    for v, c in sub_col["answers"].most_common()
                ]
                
                sub_columns_out.append({
                    "column_letter": sub_col["column_letter"],
                    "question_text": sub_col["question_text"],
                    "total_responses": sub_col["total"],
                    "answers": answer_list,
                })
            
            sub_issues_out.append({
                "name": group["name"],
                "total_responses": group["total"],
                "columns": group["columns"],
                "sub_columns": sub_columns_out,
            })

        issue_summaries.append({
            "issue_name": issue_name,
            "total_complaints": total_complaints,
            "percentage": round(percentage, 2),
            "sub_issues": sub_issues_out,
        })

    return issue_summaries


def parse_column_name(question_text: str) -> tuple:
    """
    Parse "Handle bar bend [Yes-Is vehicle fall down?]" 
    into ("Handle bar bend", "Yes-Is vehicle fall down?")
    
    Parse "Engine noise" 
    into ("Engine noise", "General")
    """
    if "[" in question_text and "]" in question_text:
        main = question_text.split("[")[0].strip()
        sub = question_text.split("[")[1].split("]")[0].strip()
        return main, sub
    return question_text.strip(), "General"