"""
L3L4 Controller – "Issue with L4, L5" PPT slide.

Counting contract
─────────────────
  L3 count   = distinct TVS respondent IDs per (issue, L3).
  L4 count   = distinct TVS respondent IDs per (issue, L3, L4).
  L5 count   = cell occurrences (TVS only, after comma-split).
               NOT deduplicated by respondent.
  L5 %       = round(L5_tvs / L3_tvs * 100)

Splitting rule (header → L3, L4, L5):
  header has [...]   → L3 = before '[', L4 = inside '[...]', L5 = cell value
  header has (...)   → L3 = before '(', L4 = inside '(...)', L5 = cell value
  else               → L3 = full header, L4 = cell value, L5 = ""

Comma-split rule (L5 only):
  L5 contains ","  → split into parts; each part is a separate row, is_split=True
  else             → single row, is_split=False
"""

import re
from typing import Dict, Any, Optional, List, Set, Tuple
from collections import defaultdict
from beanie import PydanticObjectId
from loguru import logger

from app.models.uploaded_file import UploadedFile
from app.models.survey_response import SurveyResponse
from app.utils.column_mapping import (
    get_issue_column_range_mapping,
    get_question_text_for_column,
    col_letter_to_index,
    index_to_col_letter,
)
from app.utils.query_utils import id_match, text_match
from app.utils.datetime_utils import parse_date_filter
from app.services.excel_processor import is_junk_value


class L3L4Controller:
    """Controller for L3/L4/L5 PPT slide data extraction and aggregation."""

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers (unchanged)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _clean_brand_name(brand_model: Optional[str]) -> str:
        if not brand_model:
            return "Unknown"
        cleaned = brand_model.strip()
        return cleaned if cleaned else "Unknown"

    @staticmethod
    def _is_valid_complaint(val: Any) -> bool:
        if not val:
            return False
        return not is_junk_value(val)

    @staticmethod
    def _sort_brands(brand_set: Set[str]) -> List[str]:
        """TVS first (alpha), then others (alpha)."""
        tvs_brands = sorted(
            [b for b in brand_set if b.upper().startswith("TVS")],
            key=lambda s: s.lower(),
        )
        other_brands = sorted(
            [b for b in brand_set if not b.upper().startswith("TVS")],
            key=lambda s: s.lower(),
        )
        return tvs_brands + other_brands

    @staticmethod
    def _parse_l3_l4_l5(header: str, cell_value: str) -> Tuple[str, str, str]:
        """
        Parse column header and cell value into (L3, L4, L5).

        Rule:
        - Header contains [bracket text]:
                L3 = text before '['
                L4 = text inside '[...]'
                L5 = cell_value (whitespace-collapsed)
        - Else header contains (paren text):
                L3 = text before '('
                L4 = text inside '(...)'
                L5 = cell_value (whitespace-collapsed)
        - Else (no bracket / paren):
                L3 = full header
                L4 = cell_value (whitespace-collapsed)
                L5 = ""   (blank)
        """
        header = header.strip()
        cell_collapsed = " ".join(str(cell_value).strip().split())

        bracket_match = re.search(r"^(.*?)\s*\[([^\]]+)\]", header)
        paren_match = re.search(r"^(.*?)\s*\(([^)]+)\)", header)

        if bracket_match:
            l3 = bracket_match.group(1).strip()
            l4 = bracket_match.group(2).strip()
            l5 = cell_collapsed
        elif paren_match:
            l3 = paren_match.group(1).strip()
            l4 = paren_match.group(2).strip()
            l5 = cell_collapsed
        else:
            l3 = header
            l4 = cell_collapsed
            l5 = ""

        return l3, l4, l5

    # ──────────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_l3_l4(
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
        Return L3/L4/L5 breakdown for the "Issue with L4, L5" PPT slide.

        Response shape:
        {
          "data": [
            {
              "issue_name": str,
              "tvs_total": int,
              "total_rows": int,
              "sub_issues": [
                {
                  "sub_issue": str,
                  "tvs_count": int,
                  "tvs_respondents": int,
                  "total": int,
                  "brands": [{"name": str, "count": int}],
                  "follow_ups": [
                    {
                      "follow_up": str,
                      "tvs_count": int,
                      "tvs_respondents": int,
                      "total": int,
                      "brands": [{"name": str, "count": int}],
                      "answers": [
                        {
                          "answer": str,
                          "total": int,
                          "tvs_count": int,
                          "tvs_percentage": int,
                          "is_split": bool,
                          "brands": [{"name": str, "count": int}]
                        }
                      ]
                    }
                  ]
                }
              ]
            }
          ],
          "brands": [str, ...]
        }
        """
        # ── 1. Resolve file_ids ────────────────────────────────────────────
        file_ids: List[PydanticObjectId] = []
        if file_id:
            file_ids = [PydanticObjectId(file_id)]
        elif region_id or country_id or ib_version_id:
            file_query: Dict[str, Any] = {"status": "completed"}
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

        # ── 2. Build SurveyResponse query ──────────────────────────────────
        query: Dict[str, Any] = {}
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
            date_filter: Dict[str, Any] = {}
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

        # ── 3. Load responses ──────────────────────────────────────────────
        responses = await SurveyResponse.find(query).to_list()
        if not responses:
            return {"data": [], "brands": [], "message": "No data"}

        # ── 4. Load issue column range mapping ─────────────────────────────
        issue_mapping = await get_issue_column_range_mapping()

        # Backfill complaint_groups for responses if missing
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
                        if L3L4Controller._is_valid_complaint(val):
                            cg.add(iname)
                            break
            r.complaint_groups = list(cg)

        # ── 5. Aggregation data structures ─────────────────────────────────
        #
        # row_map[(iname, l3, l4, l5_part)] = {
        #     "brand_counts": {brand: int},   ← cell count (L5)
        #     "total": int,
        #     "is_split": bool,
        # }
        #
        # l3_respondents[(iname, l3)][brand] = {respondent_id, ...}
        # l4_respondents[(iname, l3, l4)][brand] = {respondent_id, ...}
        #
        row_map: Dict[Tuple[str, str, str, str], Dict[str, Any]] = defaultdict(
            lambda: {"brand_counts": defaultdict(int), "total": 0, "is_split": False}
        )

        l3_respondents: Dict[Tuple[str, str], Dict[str, Set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )

        l4_respondents: Dict[Tuple[str, str, str], Dict[str, Set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )

        brand_set: Set[str] = set()

        target_issues = (
            [issue_name]
            if (issue_name and issue_name in issue_mapping)
            else list(issue_mapping.keys())
        )

        # ── 6. Extraction loop ─────────────────────────────────────────────
        for iname in target_issues:
            range_info = issue_mapping.get(iname, {})
            start_col = range_info.get("start")
            end_col = range_info.get("end")
            if not start_col or not end_col:
                continue

            start_idx = col_letter_to_index(start_col)
            end_idx = col_letter_to_index(end_col)

            for r in responses:
                if iname not in (r.complaint_groups or []):
                    continue
                brand = L3L4Controller._clean_brand_name(r.brand_model)
                rid = str(r.id)
                full_data = r.full_data or {}

                for col_idx in range(start_idx, end_idx + 1):
                    col_letter = index_to_col_letter(col_idx)
                    val = full_data.get(col_letter, "")
                    if not L3L4Controller._is_valid_complaint(val):
                        continue

                    header_raw = get_question_text_for_column(col_letter) or ""
                    header = str(header_raw).strip()
                    if not header or header.lower().startswith("column "):
                        continue

                    l3, l4, l5 = L3L4Controller._parse_l3_l4_l5(header, str(val))

                    # L3 / L4: respondent-level (dedup by rid)
                    l3_respondents[(iname, l3)][brand].add(rid)
                    l4_respondents[(iname, l3, l4)][brand].add(rid)

                    # L5: cell-level counts with comma-split
                    is_split = bool(l5) and "," in l5
                    if is_split:
                        raw_parts = [p.strip() for p in l5.split(",") if p.strip()]
                    elif l5:
                        raw_parts = [l5]
                    else:
                        raw_parts = [""]

                    for raw_part in raw_parts:
                        part = raw_part.strip()
                        key = (iname, l3, l4, part)
                        row_map[key]["brand_counts"][brand] += 1
                        row_map[key]["total"] += 1
                        if is_split:
                            row_map[key]["is_split"] = True

                    brand_set.add(brand)

        # ── 7. Ordered brands (TVS first, then others – both alpha) ────────
        ordered_brands = L3L4Controller._sort_brands(brand_set)

        def is_tvs(brand_name: str) -> bool:
            return brand_name.upper().startswith("TVS")

        def tvs_count_from_set_dict(set_dict: Dict[str, Set[str]]) -> int:
            return sum(len(s) for b, s in set_dict.items() if is_tvs(b))

        def tvs_count_from_count_dict(count_dict: Dict[str, int]) -> int:
            return sum(v for b, v in count_dict.items() if is_tvs(b))

        def brands_list_from_set_dict(
            set_dict: Dict[str, Set[str]]
        ) -> List[Dict[str, Any]]:
            """Respondent-level brand list (for L3 / L4)."""
            return [
                {"name": b, "count": len(set_dict.get(b, set()))}
                for b in ordered_brands
            ]

        def brands_list_from_count_dict(
            count_dict: Dict[str, int]
        ) -> List[Dict[str, Any]]:
            """Cell-level brand list (for L5)."""
            return [
                {"name": b, "count": int(count_dict.get(b, 0))}
                for b in ordered_brands
            ]

        # ── 8. Collect all distinct keys per issue ──────────────────────────
        # Group l3 names per issue
        l3_by_issue: Dict[str, Set[str]] = defaultdict(set)
        for (iname, l3) in l3_respondents:
            l3_by_issue[iname].add(l3)

        # Group l4 names per (issue, l3)
        l4_by_l3: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
        for (iname, l3, l4) in l4_respondents:
            l4_by_l3[(iname, l3)].add(l4)

        # Group l5 answers per (issue, l3, l4)
        l5_by_l4: Dict[Tuple[str, str, str], Set[str]] = defaultdict(set)
        for (iname, l3, l4, l5_part) in row_map:
            l5_by_l4[(iname, l3, l4)].add(l5_part)

        # ── 9. Build formatted_data ────────────────────────────────────────
        formatted_data: List[Dict[str, Any]] = []

        for iname, l3_names in l3_by_issue.items():

            sub_issues_list: List[Dict[str, Any]] = []
            issue_tvs_total = 0

            for l3 in l3_names:
                l3_set_dict = l3_respondents.get((iname, l3), {})
                l3_tvs_count = tvs_count_from_set_dict(l3_set_dict)
                l3_total = sum(len(s) for s in l3_set_dict.values())
                l3_brands = brands_list_from_set_dict(l3_set_dict)

                follow_ups_list: List[Dict[str, Any]] = []

                for l4 in l4_by_l3.get((iname, l3), set()):
                    l4_set_dict = l4_respondents.get((iname, l3, l4), {})
                    l4_tvs_count = tvs_count_from_set_dict(l4_set_dict)
                    l4_total = sum(len(s) for s in l4_set_dict.values())
                    l4_brands = brands_list_from_set_dict(l4_set_dict)

                    answers_list: List[Dict[str, Any]] = []

                    for l5_part in l5_by_l4.get((iname, l3, l4), set()):
                        entry = row_map.get((iname, l3, l4, l5_part), {})
                        count_dict = entry.get("brand_counts", {})
                        l5_tvs_count = tvs_count_from_count_dict(count_dict)
                        l5_total = int(entry.get("total", 0))
                        l5_is_split = bool(entry.get("is_split", False))
                        l5_pct = (
                            round(l5_tvs_count / l3_tvs_count * 100)
                            if l3_tvs_count > 0
                            else 0
                        )
                        l5_brands = brands_list_from_count_dict(dict(count_dict))

                        answers_list.append(
                            {
                                "answer": l5_part,
                                "total": l5_total,
                                "tvs_count": l5_tvs_count,
                                "tvs_percentage": l5_pct,
                                "is_split": l5_is_split,
                                "brands": l5_brands,
                            }
                        )

                    # Sort answers: tvs_count DESC, total DESC
                    answers_list.sort(
                        key=lambda x: (-x["tvs_count"], -x["total"])
                    )

                    follow_ups_list.append(
                        {
                            "follow_up": l4,
                            "tvs_count": l4_tvs_count,
                            "tvs_respondents": l4_tvs_count,
                            "total": l4_total,
                            "brands": l4_brands,
                            "answers": answers_list,
                        }
                    )

                # Sort follow_ups: tvs_count DESC
                follow_ups_list.sort(key=lambda x: -x["tvs_count"])

                sub_issues_list.append(
                    {
                        "sub_issue": l3,
                        "tvs_count": l3_tvs_count,
                        "tvs_respondents": l3_tvs_count,
                        "total": l3_total,
                        "brands": l3_brands,
                        "follow_ups": follow_ups_list,
                    }
                )
                issue_tvs_total += l3_tvs_count

            # Sort sub_issues: tvs_count DESC
            sub_issues_list.sort(key=lambda x: -x["tvs_count"])

            formatted_data.append(
                {
                    "issue_name": iname,
                    "tvs_total": issue_tvs_total,
                    "total_rows": issue_tvs_total,
                    "sub_issues": sub_issues_list,
                }
            )

        # Sort issues: tvs_total DESC
        formatted_data.sort(key=lambda x: -x["tvs_total"])

        return {
            "data": formatted_data,
            "brands": ordered_brands,
        }
