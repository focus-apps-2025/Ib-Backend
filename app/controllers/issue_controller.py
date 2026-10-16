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

# Module-level in-memory cache for issue analysis
_ANALYSIS_CACHE: Dict[str, Any] = {}


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

    @classmethod
    def invalidate_cache(cls):
        """Clear the issue analysis in-memory cache."""
        global _ANALYSIS_CACHE
        _ANALYSIS_CACHE.clear()
        logger.info("Issue analysis cache cleared.")

    @classmethod
    async def warm_cache(cls):
        """Pre-warm default analysis on server start."""
        try:
            logger.info("Pre-warming issue analysis cache in background...")
            await cls.get_issue_analysis()
            logger.success("Issue analysis cache pre-warmed successfully.")
        except Exception as e:
            logger.warning(f"Cache pre-warm warning: {e}")

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
        Optimized with MongoDB projection, column pre-indexing, single-pass aggregation,
        and server-side in-memory caching to eliminate timeouts on large datasets (5,000+ rows).
        """
        from app.config.database import db_instance
        from app.models.uploaded_file import UploadedFile
        from app.utils.column_mapping import (
            get_issue_column_range_mapping,
            get_question_text_for_column,
            col_letter_to_index,
            index_to_col_letter,
        )
        from app.services.excel_processor import is_junk_value

        # Check in-memory cache
        scoped_key = tuple(scoped_user.allowed_file_ids) if (scoped_user and scoped_user.allowed_file_ids) else None
        cache_key = f"{file_id}_{region_id}_{country_id}_{ib_version_id}_{issue_name}_{brand_model}_{survey_location}_{date_from}_{date_to}_{search}_{scoped_key}"
        if cache_key in _ANALYSIS_CACHE:
            logger.debug(f"Serving issue analysis from cache ({cache_key})")
            return _ANALYSIS_CACHE[cache_key]

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

        issue_mapping = await get_issue_column_range_mapping()

        # ─── Runtime range overrides ───
        RANGE_OVERRIDES = {
            "Pick-up problem": ("MR", "MV"), 
            "Battery issues": ("MH", "MJ"),
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
            "OA": ("Seat issue", ""),
            "OB": ("Seat issue", ""),
            "IJ": ("Front Suspension Noise", ""),
            "IK": ("Front Suspension Noise", ""),
            "IL": ("Front Suspension Noise", ""),
            "IM": ("Front Suspension Noise", ""),
            "IN": ("Oil leak from front suspension", ""),
            "IO": ("Front suspension Hard", ""),
            "IP": ("Front suspension Hard", ""),
            "IQ": ("Front suspension Hard", ""),
            "IR": ("Front Suspension Soft", ""),
            "IS": ("Front Suspension Soft", ""),
            "IT": ("Front Suspension Soft", ""),
            "IU": ("Rear Suspension Hard", ""),
            "IV": ("Rear Suspension Hard", ""),
            "IW": ("Rear Suspension Hard", ""),
            "IX": ("Rear suspension soft", ""),
            "IY": ("Rear suspension soft", ""),
            "IZ": ("Rear suspension soft", ""),
            "JA": ("Rear suspension Noise", ""),
            "JB": ("Rear suspension Noise", ""),
            "JC": ("Rear suspension Noise", ""),
            "JD": ("Rear suspension Noise", ""),
            "MR": ("less than 20km", ""),
            "MS": ("20 to 40km", ""),
            "MT": ("40 to 60km", ""),
            "MU": ("60 to 80km", ""),
            "MV": ("more than 80kmph", ""),
            "KT": ("Front Wheel Noise", ""),
            "KU": ("Front Wheel Noise", ""),
            "KV": ("Front Wheel Noise", ""),
            "KW": ("Front Wheel Wobbling", ""),
            "KX": ("Front Wheel Wobbling", ""),
            "KY": ("Front Wheel Wobbling", ""),
            "KZ": ("Front Wheel Wobbling", ""),
            "LA": ("Front Tyre Skidding", ""),
            "LB": ("Front Tyre Skidding", ""),
            "LC": ("Front Tyre Skidding", ""),
            "LD": ("Front Wheel Skidding", ""),
            "LE": ("Front Tyre Weak/Less Life", ""),
            "LF": ("Front Tyre Weak/Less Life", ""),
            "LG": ("Front Tyre Weak/Less Life", ""),
            "LH": ("Front Tyre Weak/Less Life", ""),
            "LI": ("Front Tyre Weak/Less Life", ""),
            "LJ": ("Front Tyre Weak/Less Life", ""),
            "LK": ("Front Tyre Weak/Less Life", ""),
            "LL": ("Front Wheel Tight", ""),
            "LM": ("Front Widder Tyre Required", ""),
            "LN": ("Rear Wheel Noise", ""),
            "LO": ("Rear Wheel Noise", ""),
            "LP": ("Rear Wheel Noise", ""),
            "LQ": ("Rear Wheel Wobbling", ""),
            "LR": ("Rear Wheel Wobbling", ""),
            "LS": ("Rear Wheel Wobbling", ""),
            "LT": ("Rear Wheel Wobbling", ""),
            "LU": ("Rear Tyre Skidding", ""),
            "LV": ("Rear Tyre Skidding", ""),
            "LW": ("Rear Tyre Skidding", ""),
            "LX": ("Rear Wheel Skidding", ""),
            "LY": ("Rear Tyre Weak/Less Life", ""),
            "LZ": ("Rear Tyre Weak/Less Life", ""),
            "MA": ("Rear Tyre Weak/Less Life", ""),
            "MB": ("Rear Tyre Weak/Less Life", ""),
            "MC": ("Rear Tyre Weak/Less Life", ""),
            "MD": ("Rear Tyre Weak/Less Life", ""),
            "ME": ("Rear Tyre Weak/Less Life", ""),
            "MF": ("Rear Wheel Tight", ""),
            "MG": ("Rear Widder Tyre Required", ""),
            "JX": ("Wisor Vibration", ""),
            "JY": ("Foot rest vibration", ""),
            "JZ": ("Handle bar", ""),
            "KA": ("Speedometer", ""),
            "KB": ("Juddering", ""),
            "KC": ("Seat vibration", ""),
            "KD": ("Tank vibration", ""),
            "KF": ("Clutch vibration", ""),
            "KG": ("pillion handle vibration", ""),
            "KH": ("Muffler vibration", ""),
            "KI": ("Saree guard vibration", ""),
            "KJ": ("Seat vibration", ""),
            "KL": ("LH side", ""),
            "KM": ("RH side", ""),
            "KN": ("Both side", ""),
            "JE": ("Meter noise", ""),
            "JF": ("Front mudguard", ""),
            "JG": ("Front panel noise", ""),
            "JH": ("Wisor noise", ""),
            "JI": ("Headlamp rattling noise", ""),
            "JJ": ("Floor board", ""),
            "JK": ("Lockset noise", ""),
            "JL": ("Petrol cap noise", ""),
            "JM": ("Customer unable to say", ""),
            "JO": ("Kicker noise", ""),
            "JP": ("Rear mudguard", ""),
            "JQ": ("Accessories noise", ""),
            "JR": ("Rear panel noise", ""),
            "JS": ("Seat noise", ""),
            "JT": ("Muffler noise", ""),
            "JU": ("gear box", ""),
            "JV": ("Customer unable to say", ""),
        }

        COLUMN_SHORT_LABELS = {
            "MH": "Battery drain quickly",
            "MI": "Battery life is less",
            "MJ": "Battery out of warranty",
            "NC": "Slow speed (less than 30 kmph)",
            "ND": "High speed (more than 50 kmph)",
            "NE": "During idle condition",
            "NF": "While Crossing speed breaker",
            "NG": "While De-acceleration",
            "NH": "While applying brake",
            "NI": "While applying clutch",
        }

        SKIP_COLUMNS = {"KE", "KK", "JN", "JW"}
        MERGED_COLUMN_GROUPS = [frozenset({"OA", "OB"})]

        ANSWER_VALUE_ISSUES = {
            "Jerking issues": ["ML", "MM"],
            "Low Speed": ["HY"],
            "Low speed": ["HY"],
            "Throttle / Accelerator issue": ["NJ"],
            "Seat issue": ["OA", "OB"],
            "Vehicle Pulling problem": ["OC", "OD"],
            "Low Mileage": ["HT"],
            "Kicker issues": ["HR", "HS"],
            "Wiper problem": ["OH", "OI"],
            "Roof top (soft top) issue": ["OE"],
            "Faster issue": ["OJ"],
            "Chain issue": ["FE"],
            "Chain case issue": ["FF"],
            "Battery issues": ["MH", "MI", "MJ"],
            "Running off": ["NC", "ND", "NE", "NF", "NG", "NH", "NI"],
            "Part not available": ["MP", "MQ"]
        }

        def _normalize_issue_key(name: str) -> str:
            s = str(name or '').strip().lower()
            s = s.replace(' /', '/').replace('/ ', '/')
            s = re.sub(r'\s+', ' ', s)
            s = re.sub(r'\s*issues?$', '', s)
            return s.strip()

        ANSWER_VALUE_ISSUES_NORM = {
            _normalize_issue_key(k): v for k, v in ANSWER_VALUE_ISSUES.items()
        }

        def clean_brand_name(brand_model: Optional[str]) -> str:
            if not brand_model:
                return "Unknown"
            c = brand_model.strip()
            return c if c else "Unknown"

        def is_valid_complaint(value: Any) -> bool:
            if not value:
                return False
            return not is_junk_value(value)

        def parse_column_name(question_text: str) -> tuple:
            if "[" in question_text and "]" in question_text:
                main = question_text.split("[")[0].strip()
                sub = question_text.split("[")[1].split("]")[0].strip()
                return main, sub
            if "(" in question_text and ")" in question_text:
                main = question_text.split("(")[0].strip()
                sub = question_text.split("(")[1].split(")")[0].strip()
                return main, sub
            return question_text.strip(), ""

        # Precompute static column lookup table:
        col_to_issue: Dict[str, str] = {}
        issue_to_cols: Dict[str, List[str]] = {}
        col_meta: Dict[str, tuple] = {}

        for iname, rinfo in issue_mapping.items():
            start_col = rinfo.get("start")
            end_col = rinfo.get("end")
            if not start_col or not end_col:
                continue
            s_idx = col_letter_to_index(start_col)
            e_idx = col_letter_to_index(end_col)
            issue_to_cols[iname] = []
            for c_idx in range(s_idx, e_idx + 1):
                c_let = index_to_col_letter(c_idx)
                if c_let in SKIP_COLUMNS:
                    continue
                col_to_issue[c_let] = iname
                issue_to_cols[iname].append(c_let)

                if c_let in COLUMN_SUBISSUE_OVERRIDES:
                    sub, fu = COLUMN_SUBISSUE_OVERRIDES[c_let]
                elif c_let in COLUMN_SHORT_LABELS:
                    sub = COLUMN_SHORT_LABELS[c_let]
                    fu = ""
                else:
                    qtext = get_question_text_for_column(c_let)
                    sub, fu = parse_column_name(qtext)
                col_meta[c_let] = (sub, fu)

        # Build high-performance projection: only project metadata and issue columns
        proj: Dict[str, int] = {"brand_model": 1, "complaint_groups": 1}
        for c_let in col_meta.keys():
            proj[f"full_data.{c_let}"] = 1
        for cols in ANSWER_VALUE_ISSUES.values():
            for c_let in cols:
                proj[f"full_data.{c_let}"] = 1

        # Fetch plain dicts via Motor directly (no Beanie Pydantic overhead)
        coll = db_instance.db["survey_responses"]
        responses = await coll.find(query, proj).to_list(length=None)
        if not responses:
            return {"data": [], "summary": {}, "message": "No analysis data found"}

        # Extract unique brands
        unique_brands_set = set()
        for r in responses:
            unique_brands_set.add(clean_brand_name(r.get("brand_model")))
        unique_brands = sorted(list(unique_brands_set)) if unique_brands_set else ["Unknown"]

        # Backfill complaint_groups if they have valid data in issue columns
        total_complaints_by_issue: Dict[str, int] = {}
        for r in responses:
            cg = set(r.get("complaint_groups") or [])
            fd = r.get("full_data") or {}
            for c_let, val in fd.items():
                if val and is_valid_complaint(val):
                    inm = col_to_issue.get(c_let)
                    if inm:
                        cg.add(inm)
            r["complaint_groups"] = list(cg)
            for inm in cg:
                if is_junk_value(inm):
                    continue
                if issue_name and inm.lower() != issue_name.lower():
                    continue
                total_complaints_by_issue[inm] = total_complaints_by_issue.get(inm, 0) + 1

        total_all_complaints = sum(total_complaints_by_issue.values())
        result = []

        # Process each issue
        for iname, count in total_complaints_by_issue.items():
            if issue_name and iname.lower() != issue_name.lower():
                continue

            cols = issue_to_cols.get(iname, [])
            if not cols:
                result.append({
                    "issue_name": iname,
                    "total_complaints": count,
                    "percentage": round(count / total_all_complaints * 100, 2) if total_all_complaints else 0.0,
                    "sub_issues": []
                })
                continue

            # Filter responses having this complaint
            issue_responses = [r for r in responses if iname in (r.get("complaint_groups") or [])]

            # Structures for aggregation:
            # sub_issue -> { "brands": {brand: count}, "follow_ups": {fu_name: { "brands": {brand: count}, "answers": {ans: { "brands": {brand: count}, "is_split": bool } } } }, "has_fu": bool }
            sub_issue_data: Dict[str, Dict[str, Any]] = {}

            # Answer values for issue
            answer_values_for_issue: Dict[str, Dict[str, Any]] = {}
            cols_for_answers = ANSWER_VALUE_ISSUES_NORM.get(_normalize_issue_key(iname)) or []

            for r in issue_responses:
                bm = clean_brand_name(r.get("brand_model"))
                fd = r.get("full_data") or {}
                seen_merged = set()

                for c_let in cols:
                    val = fd.get(c_let)
                    if not val or not is_valid_complaint(val):
                        continue

                    sub_issue, follow_up = col_meta.get(c_let, (c_let, ""))

                    # Merged group check
                    merged_key = None
                    for grp in MERGED_COLUMN_GROUPS:
                        if c_let in grp:
                            merged_key = grp
                            break
                    if merged_key is not None:
                        if merged_key in seen_merged:
                            continue
                        seen_merged.add(merged_key)

                    sub_dict = sub_issue_data.setdefault(sub_issue, {
                        "brands": {},
                        "follow_ups": {},
                        "has_fu": bool(follow_up)
                    })
                    sub_dict["brands"][bm] = sub_dict["brands"].get(bm, 0) + 1

                    if follow_up:
                        sub_dict["has_fu"] = True
                        fu_dict = sub_dict["follow_ups"].setdefault(follow_up, {
                            "brands": {},
                            "answers": {}
                        })
                        fu_dict["brands"][bm] = fu_dict["brands"].get(bm, 0) + 1

                        # Collect answer
                        ans_val = str(val).strip()
                        ans_val = re.sub(r'\s*-\s*', '-', ans_val)
                        if "90-50" in ans_val or "190-50" in ans_val:
                            ans_val = ans_val.replace("190-50", "40-50").replace("90-50", "40-50")

                        is_cell_split = "," in ans_val
                        parts = [a.strip() for a in ans_val.split(",") if a.strip()] if is_cell_split else [ans_val]
                        for p in parts:
                            if not p:
                                continue
                            if p not in fu_dict["answers"]:
                                fu_dict["answers"][p] = {"brands": {}, "is_split": False}
                            if is_cell_split:
                                fu_dict["answers"][p]["is_split"] = True
                            fu_dict["answers"][p]["brands"][bm] = fu_dict["answers"][p]["brands"].get(bm, 0) + 1

                # Collect answer_values_for_issue
                if cols_for_answers:
                    for c_let in cols_for_answers:
                        val = fd.get(c_let)
                        if not val or not is_valid_complaint(val):
                            continue
                        ans_key = " ".join(str(val).strip().split())
                        if not ans_key:
                            continue
                        # Case-insensitive merge onto first seen key
                        ex_key = None
                        for k in answer_values_for_issue.keys():
                            if k.lower() == ans_key.lower():
                                ex_key = k
                                break
                        if ex_key:
                            ans_key = ex_key
                        if ans_key not in answer_values_for_issue:
                            answer_values_for_issue[ans_key] = {"brands": {}, "total": 0}
                        answer_values_for_issue[ans_key]["brands"][bm] = (
                            answer_values_for_issue[ans_key]["brands"].get(bm, 0) + 1
                        )
                        answer_values_for_issue[ans_key]["total"] += 1

            # Format sub-issues list
            sub_issues_list = []
            answers_attached = False

            for sub_name, sdata in sub_issue_data.items():
                brands_list = []
                sub_total = 0
                for bname in unique_brands:
                    bcount = sdata["brands"].get(bname, 0)
                    sub_total += bcount
                    brands_list.append({"name": bname, "count": bcount})

                follow_ups_list = []
                for fu_name, fudata in sdata["follow_ups"].items():
                    fu_brands_list = []
                    fu_total = 0
                    for bname in unique_brands:
                        bcount = fudata["brands"].get(bname, 0)
                        fu_total += bcount
                        fu_brands_list.append({"name": bname, "count": bcount})

                    fu_answers = fudata["answers"]
                    has_yes_no = any(k.lower() in ("yes", "no", "y", "n") for k in fu_answers.keys())
                    if has_yes_no:
                        found_yes = any(k.lower() == "yes" for k in fu_answers.keys())
                        found_no = any(k.lower() == "no" for k in fu_answers.keys())
                        if not found_yes:
                            fu_answers["yes"] = {"brands": {}, "is_split": False}
                        if not found_no:
                            fu_answers["no"] = {"brands": {}, "is_split": False}

                    brand_totals = {}
                    for ans_val, ainfo in fu_answers.items():
                        for bname in unique_brands:
                            brand_totals[bname] = brand_totals.get(bname, 0) + ainfo["brands"].get(bname, 0)

                    answers_list = []
                    for ans_val, ainfo in fu_answers.items():
                        ans_brands_list = []
                        ans_total = 0
                        for bname in unique_brands:
                            bcount = ainfo["brands"].get(bname, 0)
                            ans_total += bcount
                            total_for_b = brand_totals.get(bname, 0)
                            pct = round((bcount / total_for_b * 100), 1) if total_for_b > 0 else 0.0
                            ans_brands_list.append({
                                "name": bname,
                                "count": bcount,
                                "percentage": pct
                            })
                        answers_list.append({
                            "answer": ans_val,
                            "total": ans_total,
                            "brands": ans_brands_list,
                            "is_split": ainfo["is_split"]
                        })

                    def sort_key(item):
                        v = item["answer"].lower()
                        if v == "yes":
                            return (0, v)
                        if v == "no":
                            return (1, v)
                        return (2, v)
                    answers_list = sorted(answers_list, key=sort_key)

                    follow_ups_list.append({
                        "follow_up": fu_name,
                        "total": fu_total,
                        "brands": fu_brands_list,
                        "answers": answers_list
                    })

                attach_answers = False
                _norm = _normalize_issue_key(iname)
                if _norm in ANSWER_VALUE_ISSUES_NORM:
                    _cols = ANSWER_VALUE_ISSUES_NORM[_norm]
                    if len(sub_issue_data) == 1:
                        attach_answers = True
                    elif len(_cols) == 1 and not answers_attached:
                        attach_answers = True
                        answers_attached = True

                sub_issues_list.append({
                    "sub_issue": sub_name,
                    "total": sub_total,
                    "brands": brands_list,
                    "has_follow_ups": sdata["has_fu"],
                    "follow_ups": follow_ups_list,
                    **({"answer_values": answer_values_for_issue} if attach_answers else {}),
                })

            if sub_issues_list:
                sub_issues_list = sorted(sub_issues_list, key=lambda x: -x["total"])

            # Per-column answer_values for Battery / Running off style issues
            if (_normalize_issue_key(iname) in ANSWER_VALUE_ISSUES_NORM and len(sub_issue_data) > 1 and len(cols_for_answers) > 1):
                for sub in sub_issues_list:
                    for r in issue_responses:
                        bm = clean_brand_name(r.get("brand_model"))
                        fd = r.get("full_data") or {}
                        for c_let in cols_for_answers:
                            parsed_main, _ = col_meta.get(c_let, (c_let, ""))
                            if parsed_main != sub["sub_issue"]:
                                continue
                            val = fd.get(c_let)
                            if not val or not is_valid_complaint(val):
                                continue
                            ans_key = " ".join(str(val).strip().split())
                            if not ans_key:
                                continue
                            sub.setdefault("answer_values", {})
                            for k in list(sub["answer_values"].keys()):
                                if k.lower() == ans_key.lower():
                                    ans_key = k
                                    break
                            if ans_key not in sub["answer_values"]:
                                sub["answer_values"][ans_key] = {"brands": {}, "total": 0}
                            sub["answer_values"][ans_key]["brands"][bm] = (
                                sub["answer_values"][ans_key]["brands"].get(bm, 0) + 1
                            )
                            sub["answer_values"][ans_key]["total"] += 1

            result.append({
                "issue_name": iname,
                "total_complaints": count,
                "percentage": round(count / total_all_complaints * 100, 2) if total_all_complaints else 0.0,
                "sub_issues": sub_issues_list
            })

        result = sorted(result, key=lambda x: -x["total_complaints"])

        payload = {
            "data": result,
            "brands": unique_brands,
            "summary": {
                "total_issues_reported": total_all_complaints,
                "unique_issues": len(result),
                "most_common_issue": result[0]["issue_name"] if result else None,
                "least_common_issue": result[-1]["issue_name"] if result else None,
            }
        }

        # Keep cache bounded to 50 entries
        if len(_ANALYSIS_CACHE) > 50:
            _ANALYSIS_CACHE.clear()
        _ANALYSIS_CACHE[cache_key] = payload

        return payload


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