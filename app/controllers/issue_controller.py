"""
Issue controller - Business logic for issue analysis.
"""
from typing import Dict, Any, Optional, List
from beanie import PydanticObjectId
from fastapi import HTTPException
from loguru import logger

from app.models.issue_analysis import IssueAnalysis
from app.models.uploaded_file import UploadedFile
from app.models.issue_mapping import IssueMapping
from app.utils.column_mapping import ISSUE_COLUMN_RANGE_MAPPING, get_question_text_for_column
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
            if region_id:
                file_query["region_id"] = PydanticObjectId(region_id)
            if country_id:
                file_query["country_id"] = PydanticObjectId(country_id)
            if ib_version_id:
                file_query["ib_version_id"] = PydanticObjectId(ib_version_id)
            files = await UploadedFile.find(file_query).to_list()
            file_ids = [f.id for f in files]

        query = {}
        if file_ids:
            query["file_id"] = {"$in": file_ids}

        if brand_model:
            query["brand_model"] = {"$regex": brand_model, "$options": "i"}
        if survey_location:
            query["survey_location"] = {"$regex": survey_location, "$options": "i"}

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

        # Fetch matching survey responses
        responses = await SurveyResponse.find(query).to_list()
        if not responses:
            return {"data": [], "summary": {}, "message": "No analysis data found"}

        issue_mapping = await get_issue_column_range_mapping()

        from app.services.excel_processor import is_junk_value

        def clean_brand_name(brand_model: str) -> str:
            if not brand_model:
                return "Unknown"
            return brand_model.strip()

        def is_valid_complaint(value: str) -> bool:
            if not value:
                return False
            return not is_junk_value(value)

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

        for iname, range_info in issue_mapping.items():
            if issue_name and iname.lower() != issue_name.lower():
                continue
            if iname not in total_complaints_by_issue:
                continue

            start_col = range_info.get("start")
            end_col = range_info.get("end")
            if not start_col or not end_col:
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
                for col_idx in range(start_idx, end_idx + 1):
                    col_letter = index_to_col_letter(col_idx)
                    val = full_data.get(col_letter, "")
                    if is_valid_complaint(val):
                        question_text = get_question_text_for_column(col_letter)
                        sub_issue, follow_up = parse_column_name(question_text)
                        
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

            sub_issues_list = []
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
                
                sub_issues_list.append({
                    "sub_issue": sub_issue_name,
                    "total": sub_total,
                    "brands": brands_list,
                    "has_follow_ups": sub_data["has_follow_ups"],
                    "follow_ups": follow_ups_list
                })

            if sub_issues_list:
                # Sort sub-issues by total complaints descending
                sub_issues_list = sorted(sub_issues_list, key=lambda x: -x["total"])
                
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
    async def get_top_issues(limit: int = 10, file_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get top issues by complaint count.
        """
        query = {}
        if file_id:
            query["file_id"] = PydanticObjectId(file_id)
            
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
    async def get_issue_trend(file_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get monthly trend data for top 5 issues.
        """
        from app.models.survey_response import SurveyResponse

        query = {}
        if file_id:
            query["file_id"] = PydanticObjectId(file_id)

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