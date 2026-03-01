"""
Judicial layer: Prosecutor, Defense, Tech Lead as distinct personas.
Each returns structured JudicialOpinion per rubric criterion via .with_structured_output().
Run as a single judicial_panel node that invokes all three in parallel (asyncio).
"""

import json
import os
from typing import Any

from pydantic import BaseModel, Field

from src.state import AgentState, Evidence, JudicialOpinion

# Schema for one judge's response: list of opinions (one per criterion)
class SingleOpinion(BaseModel):
    """One opinion for a single criterion from a judge."""
    criterion_id: str = Field(description="Rubric dimension id, e.g. git_forensic_analysis")
    score: int = Field(ge=1, le=5, description="Score 1-5 for this criterion")
    argument: str = Field(description="Brief reasoning for this score")
    cited_evidence: list[str] = Field(default_factory=list, description="Evidence IDs or quotes cited")


class JudgeVerdict(BaseModel):
    """Full verdict from one judge: one opinion per rubric dimension."""
    opinions: list[SingleOpinion] = Field(description="One opinion per criterion, in dimension order")


def _evidence_summary_for_judges(state: AgentState) -> str:
    """Build a single text summary of all evidence keyed by dimension for judge prompts."""
    evidences = state.get("evidences") or {}
    dims = state.get("rubric_dimensions") or []
    parts = []
    for dim in dims:
        dim_id = dim.get("id", "")
        dim_name = dim.get("name", "")
        parts.append(f"\n## Criterion: {dim_name} (id={dim_id})")
        for source, items in evidences.items():
            if not isinstance(items, list):
                continue
            for ev in items:
                if hasattr(ev, "model_dump"):
                    ev = ev.model_dump()
                goal = (ev.get("goal") or "").lower()
                if dim_id in goal or dim_name.lower() in goal or not dim_id:
                    parts.append(f"  [{source}] goal={ev.get('goal')} found={ev.get('found')} confidence={ev.get('confidence')}")
                    parts.append(f"    rationale: {(ev.get('rationale') or '')[:400]}")
                    if ev.get("content"):
                        parts.append(f"    content (excerpt): {str(ev.get('content'))[:500]}")
    return "\n".join(parts) if parts else "No evidence collected."


def _build_judge_prompt(evidence_summary: str, dimensions: list[dict], judge_name: str) -> str:
    """Build the user prompt for a judge with rubric context."""
    dims_text = "\n".join(
        f"- {d.get('id')}: {d.get('name')} — success: {d.get('success_pattern', '')[:150]}...; failure: {d.get('failure_pattern', '')[:150]}..."
        for d in dimensions
    )
    return f"""You are the {judge_name} in a Digital Courtroom that audits a Week 2 Automaton Auditor repository and report.

EVIDENCE COLLECTED BY DETECTIVES:
{evidence_summary}

RUBRIC DIMENSIONS (you must output exactly one opinion per dimension):
{dims_text}

Output exactly one opinion per dimension. For each dimension use its exact "id" as criterion_id. Give score 1-5, a short argument, and cite specific evidence (e.g. quote or artifact)."""


PROSECUTOR_SYSTEM = """You are the Prosecutor in a Digital Courtroom. Your core philosophy: "Trust No One. Assume Vibe Coding."
- Scrutinize evidence for gaps, security flaws, and laziness.
- If the rubric asks for "Parallel Orchestration" and evidence shows a linear pipeline, argue for Score 1.
- If Judge nodes return freeform text instead of Pydantic models, charge "Hallucination Liability" and give max 2 for Judicial Nuance.
- Be harsh: provide low scores when requirements are not met. List specific missing elements.
- Output only structured opinions (criterion_id, score 1-5, argument, cited_evidence)."""


DEFENSE_SYSTEM = """You are the Defense Attorney in a Digital Courtroom. Your core philosophy: "Reward Effort and Intent. Look for the Spirit of the Law."
- Highlight creative workarounds, deep thought, and effort even if implementation is imperfect.
- If code is buggy but the architecture report shows deep understanding, argue for a higher score.
- If Git history shows iteration and struggle, argue for "Engineering Process" and a higher score.
- Be generous where intent is clear. Output only structured opinions (criterion_id, score 1-5, argument, cited_evidence)."""


TECH_LEAD_SYSTEM = """You are the Tech Lead in a Digital Courtroom. Your core philosophy: "Does it actually work? Is it maintainable?"
- Evaluate architectural soundness, code cleanliness, and practical viability.
- Ignore "vibe" and "struggle"; focus on artifacts. Is the reducer actually used? Are tool calls safe?
- You are the tie-breaker. If Prosecutor says 1 and Defense says 5, assess technical debt and give a realistic score (1, 3, or 5).
- Provide technical remediation advice. Output only structured opinions (criterion_id, score 1-5, argument, cited_evidence)."""


def _invoke_judge(
    judge_name: str,
    system_prompt: str,
    evidence_summary: str,
    dimensions: list[dict],
) -> list[JudicialOpinion]:
    """Call LLM for one judge with structured output; return list of JudicialOpinion."""
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    structured_llm = model.with_structured_output(JudgeVerdict)
    user_msg = _build_judge_prompt(evidence_summary, dimensions, judge_name)
    try:
        messages = [
            ("system", system_prompt),
            ("human", user_msg),
        ]
        verdict = structured_llm.invoke(messages)
    except Exception as e:
        # Fallback: return one opinion per dimension with score 3 and error note
        return [
            JudicialOpinion(
                judge=judge_name,
                criterion_id=d.get("id", ""),
                score=3,
                argument=f"Judge invocation failed: {e}. Defaulting to 3.",
                cited_evidence=[],
            )
            for d in dimensions
        ]
    opinions: list[JudicialOpinion] = []
    for op in verdict.opinions:
        opinions.append(
            JudicialOpinion(
                judge=judge_name,
                criterion_id=op.criterion_id,
                score=op.score,
                argument=op.argument,
                cited_evidence=op.cited_evidence or [],
            )
        )
    # If LLM returned fewer than dimensions, fill missing with default
    dim_ids = {d.get("id") for d in dimensions}
    returned_ids = {o.criterion_id for o in opinions}
    for d in dimensions:
        if d.get("id") not in returned_ids:
            opinions.append(
                JudicialOpinion(
                    judge=judge_name,
                    criterion_id=d.get("id", ""),
                    score=3,
                    argument="No opinion returned for this criterion; default score.",
                    cited_evidence=[],
                )
            )
    return opinions


def judicial_panel_node(state: AgentState) -> dict[str, Any]:
    """
    Run Prosecutor, Defense, and Tech Lead in sequence (to avoid rate limits and ensure
    deterministic order). Each judge gets the same evidence and returns structured
    JudicialOpinion per criterion. Opinions are merged via state reducer (operator.add).
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {
            "opinions": [
                JudicialOpinion(
                    judge="Prosecutor",
                    criterion_id=d.get("id", ""),
                    score=3,
                    argument="OPENAI_API_KEY not set; judicial panel skipped.",
                    cited_evidence=[],
                )
                for d in (state.get("rubric_dimensions") or [])
            ]
        }
    dimensions = state.get("rubric_dimensions") or []
    if not dimensions:
        return {"opinions": []}
    evidence_summary = _evidence_summary_for_judges(state)
    all_opinions: list[JudicialOpinion] = []
    for name, system in [
        ("Prosecutor", PROSECUTOR_SYSTEM),
        ("Defense", DEFENSE_SYSTEM),
        ("TechLead", TECH_LEAD_SYSTEM),
    ]:
        judge_opinions = _invoke_judge(name, system, evidence_summary, dimensions)
        all_opinions.extend(judge_opinions)
    return {"opinions": all_opinions}
