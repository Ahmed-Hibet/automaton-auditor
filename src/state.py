import operator
from typing import Annotated, Dict, List, Literal, Optional
from typing_extensions import NotRequired, TypedDict
from pydantic import BaseModel, Field


# -----------------------
# Detective Output
# -----------------------

class Evidence(BaseModel):
    goal: str = Field(...)
    found: bool
    content: Optional[str] = None
    location: str
    rationale: str
    confidence: float


# -----------------------
# Judge Output
# -----------------------

class JudicialOpinion(BaseModel):
    judge: Literal["Prosecutor", "Defense", "TechLead"]
    criterion_id: str
    score: int = Field(ge=1, le=5)
    argument: str
    cited_evidence: List[str]


# -----------------------
# Chief Justice Output
# -----------------------

class CriterionResult(BaseModel):
    dimension_id: str
    dimension_name: str
    final_score: int = Field(ge=1, le=5)
    judge_opinions: List[JudicialOpinion]
    dissent_summary: Optional[str] = None
    remediation: str


class AuditReport(BaseModel):
    repo_url: str
    executive_summary: str
    overall_score: float
    criteria: List[CriterionResult]
    remediation_plan: str


# -----------------------
# Graph State
# -----------------------

class AgentState(TypedDict):
    repo_url: str
    pdf_path: str
    rubric_dimensions: List[Dict]

    # reducers prevent overwrite during parallel execution
    evidences: Annotated[
        Dict[str, List[Evidence]],
        operator.ior
    ]

    opinions: Annotated[
        List[JudicialOpinion],
        operator.add
    ]

    final_report: Optional[AuditReport]

    # Set by error-path nodes for conditional routing / reporting
    judicial_skip_reason: NotRequired[Optional[str]]