"""
Issue schemas - Issue analysis request/response models.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class IssueMappingSchema(BaseModel):
    """Issue mapping schema."""
    id: str
    issue_name: str
    column_range: Dict[str, str]
    follow_ups: List[Dict[str, Any]]
    display_order: int


class IssueListResponse(BaseModel):
    """Issue list response schema."""
    data: list[IssueMappingSchema]


class AnswerCountSchema(BaseModel):
    """Answer count schema."""
    value: str
    count: int
    percentage: float


class FollowUpAnalysisSchema(BaseModel):
    """Follow-up analysis schema."""
    question_text: str
    column_letter: str
    answers: List[AnswerCountSchema]
    total_responses: int


class IssueSummarySchema(BaseModel):
    """Issue summary schema."""
    issue_name: str
    total_complaints: int
    percentage: float
    follow_ups: List[FollowUpAnalysisSchema]


class AnalysisSummarySchema(BaseModel):
    """Analysis summary schema."""
    total_issues_reported: int
    unique_issues: int
    most_common_issue: Optional[str] = None
    least_common_issue: Optional[str] = None
    issues_per_record: float


class IssueAnalysisResponse(BaseModel):
    """Issue analysis response schema."""
    data: List[IssueSummarySchema]
    summary: AnalysisSummarySchema


class TopIssueSchema(BaseModel):
    """Top issue schema."""
    issue_name: str
    count: int


class TopIssuesResponse(BaseModel):
    """Top issues response schema."""
    data: List[TopIssueSchema]