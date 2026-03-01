"""
Judicial layer: Prosecutor, Defense, Tech Lead as explicit parallel judge nodes.
Each judge node invokes one persona and returns JudicialOpinion per rubric criterion.
Fan-out: evidence_aggregator -> prosecutor, defense, tech_lead (parallel).
Fan-in: all three -> judge_aggregator -> conditional (chief_justice | judicial_fallback).
Error paths: conditional after evidence_aggregator (missing evidence -> skip_judges);
conditional after judge_aggregator (malformed judge state -> judicial_fallback).
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


def prosecutor_node(state: AgentState) -> dict[str, Any]:
    """Single judge node: Prosecutor. Returns opinions for this judge only; state reducer merges."""
    return _single_judge_node(state, "Prosecutor", PROSECUTOR_SYSTEM)


def defense_node(state: AgentState) -> dict[str, Any]:
    """Single judge node: Defense. Returns opinions for this judge only; state reducer merges."""
    return _single_judge_node(state, "Defense", DEFENSE_SYSTEM)


def tech_lead_node(state: AgentState) -> dict[str, Any]:
    """Single judge node: Tech Lead. Returns opinions for this judge only; state reducer merges."""
    return _single_judge_node(state, "TechLead", TECH_LEAD_SYSTEM)


def _single_judge_node(
    state: AgentState, judge_name: str, system_prompt: str
) -> dict[str, Any]:
    """Invoke one judge; return its opinions. No internal handling of missing API key—caller routes via conditional edges."""
    dimensions = state.get("rubric_dimensions") or []
    if not dimensions:
        return {"opinions": []}
    evidence_summary = _evidence_summary_for_judges(state)
    opinions = _invoke_judge(judge_name, system_prompt, evidence_summary, dimensions)
    return {"opinions": opinions}


def judge_aggregator_node(state: AgentState) -> dict[str, Any]:
    """
    Fan-in node after parallel judges. No state mutation; used so conditional edge
    can run on aggregated opinions (valid vs malformed judge state).
    """
    return {}


def skip_judges_node(state: AgentState) -> dict[str, Any]:
    """
    Error path: missing evidence, missing rubric, or missing API key. Set default opinions
    so chief_justice can still produce a report; set judicial_skip_reason for summary.
    """
    dimensions = state.get("rubric_dimensions") or []
    if not os.environ.get("OPENAI_API_KEY"):
        reason = "OPENAI_API_KEY not set; judicial panel skipped (conditional edge)."
    else:
        reason = "Missing evidence or rubric; judicial panel skipped (conditional edge)."
    default_opinions = [
        JudicialOpinion(
            judge="Prosecutor",
            criterion_id=d.get("id", ""),
            score=3,
            argument=reason,
            cited_evidence=[],
        )
        for d in dimensions
    ] if dimensions else []
    return {
        "opinions": default_opinions,
        "judicial_skip_reason": reason,
    }


def judicial_fallback_node(state: AgentState) -> dict[str, Any]:
    """
    Error path: malformed judge state (e.g. missing judge, wrong opinion count).
    Ensures chief_justice has something to synthesize and records reason in state.
    """
    dimensions = state.get("rubric_dimensions") or []
    existing = list(state.get("opinions") or [])
    # Ensure at least one opinion per dimension so chief_justice can build criteria
    dim_ids = {d.get("id") for d in dimensions}
    by_criterion: dict[str, list] = {}
    for op in existing:
        by_criterion.setdefault(op.criterion_id, []).append(op)
    fallback_opinions: list[JudicialOpinion] = []
    for d in dimensions:
        dim_id = d.get("id", "")
        ops = by_criterion.get(dim_id, [])
        if len(ops) < 3:  # expect Prosecutor, Defense, TechLead
            fallback_opinions.append(
                JudicialOpinion(
                    judge="TechLead",
                    criterion_id=dim_id,
                    score=3,
                    argument="Malformed judge state (missing or inconsistent opinions); default applied.",
                    cited_evidence=[],
                )
            )
    return {
        "opinions": fallback_opinions,
        "judicial_skip_reason": "Malformed judge state; fallback opinions applied (conditional edge).",
    }


# ---------- Conditional edge routers (used by graph) ----------


def route_after_evidence_aggregator(state: AgentState) -> list[str]:
    """
    Conditional edge: after evidence_aggregator. If evidence/rubric sufficient
    and API key present, fan-out to parallel judges; else go to skip_judges (error path).
    Returns list of next node names for LangGraph add_conditional_edges.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return ["skip_judges"]
    evidences = state.get("evidences") or {}
    dimensions = state.get("rubric_dimensions") or []
    has_evidence = bool(evidences) and any(
        isinstance(v, list) and len(v) > 0 for v in evidences.values()
    )
    has_rubric = len(dimensions) > 0
    if has_evidence and has_rubric:
        return ["prosecutor", "defense", "tech_lead"]
    return ["skip_judges"]


def route_after_judge_aggregator(state: AgentState) -> list[str]:
    """
    Conditional edge: after judge_aggregator. If judge state is valid (three judges,
    one opinion per dimension per judge), go to chief_justice; else judicial_fallback.
    Returns list of one node name.
    """
    opinions = list(state.get("opinions") or [])
    dimensions = state.get("rubric_dimensions") or []
    dim_ids = [d.get("id") for d in dimensions if d.get("id")]
    if not dim_ids:
        return ["judicial_fallback"]
    expected_per_judge = len(dim_ids)
    judge_names = {"Prosecutor", "Defense", "TechLead"}
    by_judge: dict[str, list] = {j: [] for j in judge_names}
    for op in opinions:
        if op.judge in by_judge:
            by_judge[op.judge].append(op)
    # Valid: each judge has exactly expected_per_judge opinions, and criterion_ids match
    valid = all(len(by_judge[j]) == expected_per_judge for j in judge_names)
    if valid:
        for j in judge_names:
            ids = {o.criterion_id for o in by_judge[j]}
            if ids != set(dim_ids):
                valid = False
                break
    if valid:
        return ["chief_justice"]
    return ["judicial_fallback"]
