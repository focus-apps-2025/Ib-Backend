"""
Issue controller - Business logic for issue analysis.
"""
import re
from typing import Dict, Any, Optional, List
from beanie import PydanticObjectId
from fastapi import HTTPException
from loguru import logger

from app.models.issue_analysis import IssueAnalysis
from app.models.uploaded_file import UploadedFile
from app.models.issue_mapping import IssueMapping
from app.utils.column_mapping import ISSUE_COLUMN_RANGE_MAPPING, get_question_text_for_column
from app.utils.query_utils import id_match, text_match
from app.utils.datetime_utils import parse_date_filter


class IssueController:
    """Controller for issue analysis operations."""
    
    @staticmethod
    async def list_issues() -> Dict[str, Any]:
        """
        List all issue definitions with column ranges.
        """
        issues = await IssueMapping.find_all().sort("+display_order").to_list()
        if not issues:
            # Return from static mapping if DB not seeded
            return {
                "data": [
                    {
                        "issue_name": name,
                        "column_range": info,
                        "display_order": idx,
                    }
                    for idx, (name, info) in enumerate(ISSUE_COLUMN_RANGE_MAPPING.items())
                ]
            }
        return {
            "data": [
                {
                    "id": str(i.id),
                    "issue_name": i.issue_name,
                    "column_range": i.column_range.model_dump() if i.column_range else {},
                    "follow_ups": [
                        {
                            "column_letter": f.column_letter,
                            "question_text": get_question_text_for_column(f.column_letter) if (not f.question_text or f.question_text.startswith("Column ")) else f.question_text,
                            "display_order": f.display_order,
                        }
                        for f in i.follow_ups
                    ],
                    "display_order": i.display_order,
                }
                for i in issues
            ]
        }

    @staticmethod
    async def get_issue_analysis(
        file_id: Optional[str] = None,
        region_id: Optional[str] = None,
        country_id: Optional[str] = None,
        ib_version_id: Optional[str] = None,
        issue_name: Optional[str] = None,
        brand_model: Optional[str] = None,
        survey_location: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        search: Optional[str] = None,
        scoped_user: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Get issue analysis with brand-wise breakdown of sub-issues on the fly.
        """
        from app.models.survey_response import SurveyResponse
        from app.models.uploaded_file import UploadedFile
        from app.utils.column_mapping import get_issue_column_range_mapping, get_question_text_for_column, col_letter_to_index, index_to_col_letter

        file_ids = []
        if file_id:
            file_ids = [PydanticObjectId(file_id)]
        elif region_id or country_id or ib_version_id:
            file_query = {"status": "completed"}
            r_match = id_match(region_id)
            if r_match is not None:
                file_query["region_id"] = r_match
            c_match = id_match(country_id)
            if c_match is not None:
                file_query["country_id"] = c_match
            ib_match = id_match(ib_version_id)
            if ib_match is not None:
                file_query["ib_version_id"] = ib_match
            files = await UploadedFile.find(file_query).to_list()
            file_ids = [f.id for f in files]

        query = {}
        if file_ids:
            query["file_id"] = {"$in": file_ids}
        elif region_id or country_id or ib_version_id:
            query["file_id"] = {"$in": []}

        brand_match = text_match(brand_model)
        if brand_match is not None:
            query["brand_model"] = brand_match
        location_match = text_match(survey_location)
        if location_match is not None:
            query["survey_location"] = location_match

        if date_from or date_to:
            date_filter = {}
            if date_from:
                date_filter["$gte"] = parse_date_filter(date_from)
            if date_to:
                date_filter["$lte"] = parse_date_filter(date_to)
            query["survey_date"] = date_filter

        if search:
            query["$or"] = [
                {"brand_model": {"$regex": search, "$options": "i"}},
                {"survey_location": {"$regex": search, "$options": "i"}},
                {"user_name": {"$regex": search, "$options": "i"}},
                {"vin_number": {"$regex": search, "$options": "i"}},
            ]

        if scoped_user:
            query = scoped_user.apply_to_query(query)

        # Fetch matching survey responses
        responses = await SurveyResponse.find(query).to_list()
        if not responses:
            return {"data": [], "summary": {}, "message": "No analysis data found"}

        issue_mapping = await get_issue_column_range_mapping()
        # ─── Runtime range overrides ───
        # Shrink an issue's column range without touching column_mapping.py
        # or the DB. Keyed by issue_name → (start_col, end_col).
        RANGE_OVERRIDES = {
            "Pick-up problem": ("MR", "MV"),   # only the speed-bracket columns
        }
        for _name, (_start, _end) in RANGE_OVERRIDES.items():
            if _name in issue_mapping:
                issue_mapping[_name] = {
                    **issue_mapping[_name],
                    "start": _start,
                    "end": _end,
                    "count": col_letter_to_index(_end) - col_letter_to_index(_start) + 1,
                }
        COLUMN_SUBISSUE_OVERRIDES = {
            # Seat issue: OA + OB → single "Seat issue" entry
            "OA": ("Seat issue", ""),
            "OB": ("Seat issue", ""),

            # ─── Suspension issue (IJ → JD): merge 21 columns into 7 sub-issues ───
            # Front Suspension Noise: IJ, IK, IL, IM
            "IJ": ("Front Suspension Noise", ""),
            "IK": ("Front Suspension Noise", ""),
            "IL": ("Front Suspension Noise", ""),
            "IM": ("Front Suspension Noise", ""),

            # Oil leak from front suspension: IN (standalone)
            "IN": ("Oil leak from front suspension", ""),

            # Front suspension Hard: IO, IP, IQ
            "IO": ("Front suspension Hard", ""),
            "IP": ("Front suspension Hard", ""),
            "IQ": ("Front suspension Hard", ""),

            # Front Suspension Soft: IR, IS, IT
            "IR": ("Front Suspension Soft", ""),
            "IS": ("Front Suspension Soft", ""),
            "IT": ("Front Suspension Soft", ""),

            # Rear Suspension Hard: IU, IV, IW
            "IU": ("Rear Suspension Hard", ""),
            "IV": ("Rear Suspension Hard", ""),
            "IW": ("Rear Suspension Hard", ""),

            # Rear suspension soft: IX, IY, IZ
            "IX": ("Rear suspension soft", ""),
            "IY": ("Rear suspension soft", ""),
            "IZ": ("Rear suspension soft", ""),

            # Rear suspension Noise: JA, JB, JC, JD
            "JA": ("Rear suspension Noise", ""),
            "JB": ("Rear suspension Noise", ""),
            "JC": ("Rear suspension Noise", ""),
            "JD": ("Rear suspension Noise", ""),
            # Pickup-problem
            "MR": ("less than 20km",   ""),
            "MS": ("20 to 40km",       ""),
            "MT": ("40 to 60km",       ""),
            "MU": ("60 to 80km",       ""),
            "MV": ("more than 80kmph", ""),

                        # ─── Wheel/Tyre issues (KT → MG): merge into 14 sub-issues ───

            # Front Wheel Noise: KT, KU, KV
            "KT": ("Front Wheel Noise", ""),
            "KU": ("Front Wheel Noise", ""),
            "KV": ("Front Wheel Noise", ""),

            # Front Wheel Wobbling: KW, KX, KY, KZ
            "KW": ("Front Wheel Wobbling", ""),
            "KX": ("Front Wheel Wobbling", ""),
            "KY": ("Front Wheel Wobbling", ""),
            "KZ": ("Front Wheel Wobbling", ""),

            # Front Tyre Skidding: LA, LB, LC
            "LA": ("Front Tyre Skidding", ""),
            "LB": ("Front Tyre Skidding", ""),
            "LC": ("Front Tyre Skidding", ""),

            # Front Wheel Skidding: LD (standalone)
            "LD": ("Front Wheel Skidding", ""),

            # Front Tyre Weak / Less Life: LE..LK
            "LE": ("Front Tyre Weak/Less Life", ""),
            "LF": ("Front Tyre Weak/Less Life", ""),
            "LG": ("Front Tyre Weak/Less Life", ""),
            "LH": ("Front Tyre Weak/Less Life", ""),
            "LI": ("Front Tyre Weak/Less Life", ""),
            "LJ": ("Front Tyre Weak/Less Life", ""),
            "LK": ("Front Tyre Weak/Less Life", ""),

            # Front Wheel Tight: LL
            "LL": ("Front Wheel Tight", ""),

            # Front Widder Tyre Required: LM
            "LM": ("Front Widder Tyre Required", ""),

            # Rear Wheel Noise: LN, LO, LP
            "LN": ("Rear Wheel Noise", ""),
            "LO": ("Rear Wheel Noise", ""),
            "LP": ("Rear Wheel Noise", ""),

            # Rear Wheel Wobbling: LQ..LT
            "LQ": ("Rear Wheel Wobbling", ""),
            "LR": ("Rear Wheel Wobbling", ""),
            "LS": ("Rear Wheel Wobbling", ""),
            "LT": ("Rear Wheel Wobbling", ""),

            # Rear Tyre Skidding: LU, LV, LW
            "LU": ("Rear Tyre Skidding", ""),
            "LV": ("Rear Tyre Skidding", ""),
            "LW": ("Rear Tyre Skidding", ""),

            # Rear Wheel Skidding: LX (standalone)
            "LX": ("Rear Wheel Skidding", ""),

            # Rear Tyre Weak / Less Life: LY..ME
            "LY": ("Rear Tyre Weak/Less Life", ""),
            "LZ": ("Rear Tyre Weak/Less Life", ""),
            "MA": ("Rear Tyre Weak/Less Life", ""),
            "MB": ("Rear Tyre Weak/Less Life", ""),
            "MC": ("Rear Tyre Weak/Less Life", ""),
            "MD": ("Rear Tyre Weak/Less Life", ""),
            "ME": ("Rear Tyre Weak/Less Life", ""),

            # Rear Wheel Tight: MF
            "MF": ("Rear Wheel Tight", ""),

            # Rear Widder Tyre Required: MG
            "MG": ("Rear Widder Tyre Required", ""),
        }

        MERGED_COLUMN_GROUPS = [
            {"OA", "OB"},                     # Seat issue
        ]

        COLUMN_SHORT_LABELS = {
            # Battery
            "MH": "Battery drain quickly",
            "MI": "Battery life is less",
            "MJ": "Battery out of warranty",
            # Running off
            "NC": "Slow speed (less than 30 kmph)",
            "ND": "High speed (more than 50 kmph)",
            "NE": "During idle condition",
            "NF": "While Crossing speed breaker",
            "NG": "While De-acceleration",
            "NH": "While applying brake",
            "NI": "While applying clutch",
        }

                # ─── Columns whose raw cell values should be collected as
        #     "answer_values" for the PPT answer-wise slides ───
        ANSWER_VALUE_ISSUES = {
            # issue_name : [list of columns to collect answers from]
            "Jerking issues":              ["ML", "MM"],
            "Low Speed":                   ["HY"],
            "Low speed":                   ["HY"],
            "Throttle / Accelerator issue": ["NJ"],
            "Seat issue":                  ["OA", "OB"],
            "Vehicle Pulling problem":     ["OC", "OD"],
            "Low Mileage":                 ["HT"],
            "Kicker issues":               ["HR", "HS"],
            "Wiper problem":               ["OH", "OI"],
            "Roof top (soft top) issue":   ["OE"],
            "Faster issue":                ["OJ"],
            "Chain issue":                 ["FE"],
            "Chain case issue":            ["FF"],
            "Battery issues":              ["MH", "MI", "MJ"],
            "Running off":                 ["NC", "ND", "NE", "NF", "NG", "NH", "NI"],
            "Part not available":          ["MP", "MQ"]
        }
        def _normalize_issue_key(name: str) -> str:
            """Lowercase + strip trailing 'issue(s)' + collapse whitespace +
            remove spaces around slashes. Used to match the frontend config
            regardless of formatting differences."""
            s = str(name or '').strip().lower()
            s = s.replace(' /', '/').replace('/ ', '/')   # tighten slashes
            s = re.sub(r'\s+', ' ', s)                    # collapse whitespace
            s = re.sub(r'\s*issues?$', '', s)             # strip trailing issue(s)
            return s.strip()

        # Pre-normalize the keys once so lookups are O(1)
        ANSWER_VALUE_ISSUES_NORM = {
            _normalize_issue_key(k): v for k, v in ANSWER_VALUE_ISSUES.items()
        }

        from app.services.excel_processor import is_junk_value

        def clean_brand_name(brand_model: str) -> str:
            if not brand_model:
                return "Unknown"
            return brand_model.strip()

        def is_valid_complaint(value: str) -> bool:
            if not value:
                return False
            return not is_junk_value(value)

        # Backfill complaint_groups if they have valid data in the issue column ranges but missed the main checkbox
        for r in responses:
            cg = set(r.complaint_groups or [])
            for iname, range_info in issue_mapping.items():
                if iname in cg:
                    continue
                start_col = range_info.get("start")
                end_col = range_info.get("end")
                if start_col and end_col:
                    start_idx = col_letter_to_index(start_col)
                    end_idx = col_letter_to_index(end_col)
                    for col_idx in range(start_idx, end_idx + 1):
                        col_letter = index_to_col_letter(col_idx)
                        val = (r.full_data or {}).get(col_letter, "")
                        if is_valid_complaint(val):
                            cg.add(iname)
                            break
            r.complaint_groups = list(cg)

        # Count total complaints per issue
        total_complaints_by_issue = {}
        for r in responses:
            complaint_groups = r.complaint_groups or []
            for iname in complaint_groups:
                if is_junk_value(iname):
                    continue
                if issue_name and iname.lower() != issue_name.lower():
                    continue
                total_complaints_by_issue[iname] = total_complaints_by_issue.get(iname, 0) + 1

        # Extract all column headers mapping and parse sub-issues
        # We use the global get_question_text_for_column function.

        # Helper to parse column name into base sub-issue and follow-up
        def parse_column_name(question_text: str) -> tuple:
            """
            Parse "Speedo cable [less life]" -> ("Speedo cable", "less life")
            Parse "Clutch loose (Remarks)" -> ("Clutch loose", "Remarks")
            Parse "Front brake noise" -> ("Front brake noise", "")
            """
            # Handle [brackets]
            if "[" in question_text and "]" in question_text:
                main = question_text.split("[")[0].strip()
                sub = question_text.split("[")[1].split("]")[0].strip()
                return main, sub
            # Handle (parentheses)
            if "(" in question_text and ")" in question_text:
                main = question_text.split("(")[0].strip()
                sub = question_text.split("(")[1].split(")")[0].strip()
                return main, sub
            # No brackets/parentheses
            return question_text.strip(), ""

        # Extract all unique brand names in the matching responses
        unique_brands = sorted(list(set(clean_brand_name(r.brand_model) for r in responses)))
        if not unique_brands:
            unique_brands = ["Unknown"]

        # Group responses by issue, sub-issue, and brand
        result = []
        total_all_complaints = sum(total_complaints_by_issue.values())

        for iname, count in total_complaints_by_issue.items():
            if issue_name and iname.lower() != issue_name.lower():
                continue

            range_info = issue_mapping.get(iname) or {}
            start_col = range_info.get("start")
            end_col = range_info.get("end")
            
            if not start_col or not end_col:
                result.append({
                    "issue_name": iname,
                    "total_complaints": count,
                    "percentage": round(count / total_all_complaints * 100, 2) if total_all_complaints else 0.0,
                    "sub_issues": []
                })
                continue

            start_idx = col_letter_to_index(start_col)
            end_idx = col_letter_to_index(end_col)

            # Structure: sub_issue -> brand -> count, plus follow_ups if any
            sub_issue_data = {}
            issue_responses = [r for r in responses if iname in (r.complaint_groups or [])]

            for r in issue_responses:
                brand_model = r.brand_model
                brand_name = clean_brand_name(brand_model)
                full_data = r.full_data or {}

                # Collect valid complaints in the issue's column range
                seen_merged_groups = set()

                for col_idx in range(start_idx, end_idx + 1):
                    col_letter = index_to_col_letter(col_idx)
                    val = full_data.get(col_letter, "")
                    if not is_valid_complaint(val):
                        continue

                        # ── Apply column override / merge logic ──
                    if col_letter in COLUMN_SUBISSUE_OVERRIDES:
                        sub_issue, follow_up = COLUMN_SUBISSUE_OVERRIDES[col_letter]
                    elif col_letter in COLUMN_SHORT_LABELS:
                        sub_issue = COLUMN_SHORT_LABELS[col_letter]
                        follow_up = ""
                    else:
                        question_text = get_question_text_for_column(col_letter)
                        sub_issue, follow_up = parse_column_name(question_text)
                    # If this column belongs to a merged group, only count the group once per respondent
                    merged_group_key = None
                    for grp in MERGED_COLUMN_GROUPS:
                        if col_letter in grp:
                            merged_group_key = frozenset(grp)
                            break

                    if merged_group_key is not None:
                        if merged_group_key in seen_merged_groups:
                            continue  # already counted this merged group for this respondent
                        seen_merged_groups.add(merged_group_key)
                        
                    if sub_issue not in sub_issue_data:
                        sub_issue_data[sub_issue] = {
                            "brands": {},
                            "follow_ups": {},
                            "has_follow_ups": bool(follow_up)
                        }
                        
                    sub_issue_data[sub_issue]["brands"][brand_name] = sub_issue_data[sub_issue]["brands"].get(brand_name, 0) + 1
                        
                    if follow_up:
                        if follow_up not in sub_issue_data[sub_issue]["follow_ups"]:
                            sub_issue_data[sub_issue]["follow_ups"][follow_up] = {}
                        sub_issue_data[sub_issue]["follow_ups"][follow_up][brand_name] = sub_issue_data[sub_issue]["follow_ups"][follow_up].get(brand_name, 0) + 1
                        # ─── Build answer_values for the PPT answer-wise slides ───
            # Collected per-issue, across the configured columns.
            answer_values_for_issue: Dict[str, Dict[str, Any]] = {}
            cols_for_answers = ANSWER_VALUE_ISSUES_NORM.get(_normalize_issue_key(iname))

            if cols_for_answers:
                for r in responses:
                    brand_name = clean_brand_name(r.brand_model)
                    full_data = r.full_data or {}
                    for col_letter in cols_for_answers:
                        val = full_data.get(col_letter, "")
                        if not is_valid_complaint(val):
                            continue
                        # Normalize: trim + collapse internal whitespace
                        answer_key = str(val).strip()
                        answer_key = " ".join(answer_key.split())
                        if not answer_key:
                            continue

                        # Merge case-insensitively onto the first-seen display form
                        existing_key = None
                        for k in answer_values_for_issue.keys():
                            if k.lower() == answer_key.lower():
                                existing_key = k
                                break
                        if existing_key:
                            answer_key = existing_key

                        if answer_key not in answer_values_for_issue:
                            answer_values_for_issue[answer_key] = {
                                "brands": {},
                                "total": 0,
                            }
                        answer_values_for_issue[answer_key]["brands"][brand_name] = (
                            answer_values_for_issue[answer_key]["brands"].get(brand_name, 0) + 1
                        )
                        answer_values_for_issue[answer_key]["total"] += 1

            sub_issues_list = []
            answers_attached = False 
            for sub_issue_name, sub_data in sub_issue_data.items():
                # Build brands list dynamically
                brands_list = []
                sub_total = 0
                for bname in unique_brands:
                    bcount = sub_data["brands"].get(bname, 0)
                    sub_total += bcount
                    brands_list.append({"name": bname, "count": bcount})
                
                # Build follow-ups array WITH answers
                follow_ups_list = []
                for fu_name, fu_brands in sub_data["follow_ups"].items():
                    fu_brands_list = []
                    fu_total = 0
                    for bname in unique_brands:
                        bcount = fu_brands.get(bname, 0)
                        fu_total += bcount
                        fu_brands_list.append({"name": bname, "count": bcount})
                    
                    # Collect answer-wise breakdown for this follow-up
                    fu_answers = {}
                    
                    # Loop through responses again to get answers for this follow-up
                    for r in issue_responses:
                        brand_name = clean_brand_name(r.brand_model)
                        full_data = r.full_data or {}
                        
                        # Find the column for this follow-up
                        for col_idx in range(start_idx, end_idx + 1):
                            col_letter = index_to_col_letter(col_idx)
                            val = full_data.get(col_letter, "")
                            if is_valid_complaint(val):
                                question_text = get_question_text_for_column(col_letter)
                                sub_issue_check, follow_up_check = parse_column_name(question_text)
                                
                                # Check if this is the current follow-up
                                if sub_issue_check == sub_issue_name and follow_up_check == fu_name:
                                    # Get the answer value from the column

                                    answer_value = str(val).strip()
                                    
                                    # Normalize spaces around hyphens and fix known typos
                                    answer_value = re.sub(r'\s*-\s*', '-', answer_value)
                                    if "90-50" in answer_value or "190-50" in answer_value:
                                        answer_value = answer_value.replace("190-50", "40-50").replace("90-50", "40-50")
                                    
                                    # Split comma-separated values into separate answers
                                    is_cell_split = "," in answer_value
                                    if is_cell_split:
                                        parts = [a.strip() for a in answer_value.split(",") if a.strip()]
                                    else:
                                        parts = [answer_value]
                                        
                                    for part in parts:
                                        if part not in fu_answers:
                                            fu_answers[part] = {"brands": {}, "is_split": False}
                                        if is_cell_split:
                                            fu_answers[part]["is_split"] = True
                                        fu_answers[part]["brands"][brand_name] = fu_answers[part]["brands"].get(brand_name, 0) + 1
                    
                    # Ensure yes/no are both present if it's a binary yes/no follow-up
                    has_yes_no = False
                    for ans_val in fu_answers.keys():
                        if ans_val.lower() in ("yes", "no", "y", "n"):
                            has_yes_no = True
                            break
                    if has_yes_no:
                        found_yes = False
                        found_no = False
                        for ans_val in list(fu_answers.keys()):
                            if ans_val.lower() == "yes":
                                found_yes = True
                            elif ans_val.lower() == "no":
                                found_no = True
                        if not found_yes:
                            fu_answers["yes"] = {"brands": {}, "is_split": False}
                        if not found_no:
                            fu_answers["no"] = {"brands": {}, "is_split": False}

                    # Calculate total answers per brand for this follow-up
                    brand_totals = {}
                    for ans_value, ans_info in fu_answers.items():
                        for bname in unique_brands:
                            brand_totals[bname] = brand_totals.get(bname, 0) + ans_info["brands"].get(bname, 0)

                    # Build answers array
                    answers_list = []
                    for ans_value, ans_info in fu_answers.items():
                        ans_brands_list = []
                        ans_total = 0
                        for bname in unique_brands:
                            bcount = ans_info["brands"].get(bname, 0)
                            ans_total += bcount
                            
                            # calculate brand percentage
                            total_for_brand = brand_totals.get(bname, 0)
                            pct = round((bcount / total_for_brand * 100), 1) if total_for_brand > 0 else 0.0
                            
                            ans_brands_list.append({
                                "name": bname,
                                "count": bcount,
                                "percentage": pct
                            })
                        answers_list.append({
                            "answer": ans_value,
                            "total": ans_total,
                            "brands": ans_brands_list,
                            "is_split": ans_info["is_split"]
                        })
                    
                    # Sort the answers array so "yes" comes first, "no" second, and any other values follow.
                    def sort_key(item):
                        val = item["answer"].lower()
                        if val == "yes":
                            return (0, val)
                        if val == "no":
                            return (1, val)
                        return (2, val)
                    answers_list = sorted(answers_list, key=sort_key)
                    
                    follow_ups_list.append({
                        "follow_up": fu_name,
                        "total": fu_total,
                        "brands": fu_brands_list,
                        "answers": answers_list
                    })
                
                               # Determine whether to attach answer_values to this sub-issue.
                # Attach on:
                #   - merged issues (Seat / Jerking / etc.): the single sub-issue
                #   - single-column issues: the one sub-issue built from that column
                #   - per-column issues (Battery / Running off): attach to every sub-issue
               # NEW
                attach_answers = False
                _norm = _normalize_issue_key(iname)
                if _norm in ANSWER_VALUE_ISSUES_NORM:
                    _cols = ANSWER_VALUE_ISSUES_NORM[_norm]
                    if len(sub_issue_data) == 1:
                        attach_answers = True
                    elif len(_cols) == 1 and not answers_attached:
                        # Single-column issue (e.g. Faster issue -> OJ): attach once,
                        # so answers are never duplicated or double-counted
                        attach_answers = True
                        answers_attached = True
                
                sub_issues_list.append({
                    "sub_issue": sub_issue_name,
                    "total": sub_total,
                    "brands": brands_list,
                    "has_follow_ups": sub_data["has_follow_ups"],
                    "follow_ups": follow_ups_list,
                    **({"answer_values": answer_values_for_issue} if attach_answers else {}),
                })
            # Sort sub-issues by total complaints descending
            if sub_issues_list:
                sub_issues_list = sorted(sub_issues_list, key=lambda x: -x["total"])
                        # ─── Per-column answer_values for Battery / Running off style issues ───
            if (_normalize_issue_key(iname) in ANSWER_VALUE_ISSUES_NORM and len(sub_issue_data) > 1 and len(ANSWER_VALUE_ISSUES_NORM[_normalize_issue_key(iname)]) > 1):
                cols_for_per_col = ANSWER_VALUE_ISSUES_NORM.get(_normalize_issue_key(iname)) or []

                for sub in sub_issues_list:
                    # Find the column whose parsed sub_issue matches this sub
                    for r in issue_responses:
                        brand_name = clean_brand_name(r.brand_model)
                        full_data = r.full_data or {}
                        for col_letter in cols_for_per_col:
                            qtext = get_question_text_for_column(col_letter)
                            parsed_main, _ = parse_column_name(qtext)
                            if parsed_main != sub["sub_issue"]:
                                continue
                            val = full_data.get(col_letter, "")
                            if not is_valid_complaint(val):
                                continue
                            answer_key = " ".join(str(val).strip().split())
                            if not answer_key:
                                continue

                            sub.setdefault("answer_values", {})
                            for k in list(sub["answer_values"].keys()):
                                if k.lower() == answer_key.lower():
                                    answer_key = k
                                    break
                            if answer_key not in sub["answer_values"]:
                                sub["answer_values"][answer_key] = {"brands": {}, "total": 0}
                            sub["answer_values"][answer_key]["brands"][brand_name] = (
                                sub["answer_values"][answer_key]["brands"].get(brand_name, 0) + 1
                            )
                            sub["answer_values"][answer_key]["total"] += 1
            result.append({
                "issue_name": iname,
                "total_complaints": total_complaints_by_issue[iname],
                "percentage": round(total_complaints_by_issue[iname] / total_all_complaints * 100, 2) if total_all_complaints else 0.0,
                "sub_issues": sub_issues_list
            })

        # Sort results by total_complaints descending
        result = sorted(result, key=lambda x: -x["total_complaints"])

        return {
            "data": result,
            "brands": unique_brands,
            "summary": {
                "total_issues_reported": total_all_complaints,
                "unique_issues": len(result),
                "most_common_issue": result[0]["issue_name"] if result else None,
                "least_common_issue": result[-1]["issue_name"] if result else None,
            }
        }


    @staticmethod
    async def get_top_issues(limit: int = 10, file_id: Optional[str] = None, scoped_user: Optional[Any] = None) -> Dict[str, Any]:
        """
        Get top issues by complaint count.
        """
        query = {}
        if file_id:
            query["file_id"] = PydanticObjectId(file_id)
        if scoped_user and scoped_user.allowed_file_ids is not None:
            if "file_id" in query:
                if query["file_id"] not in scoped_user.allowed_file_ids:
                    return {"data": []}
            else:
                query["file_id"] = {"$in": scoped_user.allowed_file_ids}

        analyses = await IssueAnalysis.find(query).to_list()

        counts: dict = {}
        for analysis in analyses:
            for issue in analysis.issues:
                counts[issue.issue_name] = counts.get(issue.issue_name, 0) + issue.total_complaints

        top = sorted(counts.items(), key=lambda x: -x[1])[:limit]
        return {
            "data": [{"issue_name": n, "count": c} for n, c in top]
        }

    @staticmethod
    async def get_issue_trend(file_id: Optional[str] = None, scoped_user: Optional[Any] = None) -> Dict[str, Any]:
        """
        Get monthly trend data for top 5 issues.
        """
        from app.models.survey_response import SurveyResponse

        query = {}
        if file_id:
            query["file_id"] = PydanticObjectId(file_id)

        if scoped_user:
            query = scoped_user.apply_to_query(query)

        pipeline = [
            {"$match": query},
            {"$unwind": "$complaint_groups"},
            {
                "$group": {
                    "_id": {
                        "issue": "$complaint_groups",
                        "year": {"$year": "$survey_date"},
                        "month": {"$month": "$survey_date"},
                    },
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"_id.year": 1, "_id.month": 1}},
        ]
        results = await SurveyResponse.aggregate(pipeline).to_list()
        return {"data": results}