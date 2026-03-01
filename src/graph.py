"""
Full StateGraph: Detectives (parallel) -> EvidenceAggregator -> [conditional] -> Judges (parallel) -> JudgeAggregator -> [conditional] -> Chief Justice -> END.
- Detective fan-out: RepoInvestigator, DocAnalyst, VisionInspector run in parallel; fan-in to EvidenceAggregator.
- Conditional after EvidenceAggregator: missing evidence / no rubric -> skip_judges; else fan-out to Prosecutor, Defense, TechLead.
- Judicial fan-in: all three judges -> judge_aggregator; conditional: malformed judge state -> judicial_fallback, else chief_justice.
- Error paths: skip_judges and judicial_fallback both rejoin at chief_justice for a single report.
"""

import json
from pathlib import Path

from langgraph.graph import START, END, StateGraph

from src.state import AgentState
from src.nodes.detectives import (
    repo_investigator_node,
    doc_analyst_node,
    vision_inspector_node,
    evidence_aggregator_node,
)
from src.nodes.judges import (
    prosecutor_node,
    defense_node,
    tech_lead_node,
    judge_aggregator_node,
    skip_judges_node,
    judicial_fallback_node,
    route_after_evidence_aggregator,
    route_after_judge_aggregator,
)
from src.nodes.justice import chief_justice_node


def _load_rubric_dimensions() -> list[dict]:
    """Load rubric dimensions from config for detective targeting."""
    paths = [
        Path(__file__).resolve().parent.parent / "config" / "rubric.json",
        Path("config/rubric.json"),
    ]
    for p in paths:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data.get("dimensions", [])
            except Exception:
                pass
    return []


def build_graph():
    builder = StateGraph(AgentState)

    # Layer 1: Detective nodes
    builder.add_node("repo_investigator", repo_investigator_node)
    builder.add_node("doc_analyst", doc_analyst_node)
    builder.add_node("vision_inspector", vision_inspector_node)
    builder.add_node("evidence_aggregator", evidence_aggregator_node)
    # Layer 2: Judicial — explicit parallel judge nodes + fan-in + error paths
    builder.add_node("prosecutor", prosecutor_node)
    builder.add_node("defense", defense_node)
    builder.add_node("tech_lead", tech_lead_node)
    builder.add_node("judge_aggregator", judge_aggregator_node)
    builder.add_node("skip_judges", skip_judges_node)
    builder.add_node("judicial_fallback", judicial_fallback_node)
    # Layer 3: Synthesis
    builder.add_node("chief_justice", chief_justice_node)

    # Detective fan-out from START
    builder.add_conditional_edges(
        START,
        lambda _: ["repo_investigator", "doc_analyst", "vision_inspector"],
    )

    # Detective fan-in: all detectives -> evidence_aggregator
    builder.add_edge("repo_investigator", "evidence_aggregator")
    builder.add_edge("doc_analyst", "evidence_aggregator")
    builder.add_edge("vision_inspector", "evidence_aggregator")

    # Conditional: after evidence_aggregator — missing evidence -> skip_judges; else fan-out to judges
    builder.add_conditional_edges(
        "evidence_aggregator",
        route_after_evidence_aggregator,
    )

    # Judicial fan-in: all three judges -> judge_aggregator
    builder.add_edge("prosecutor", "judge_aggregator")
    builder.add_edge("defense", "judge_aggregator")
    builder.add_edge("tech_lead", "judge_aggregator")

    # Conditional: after judge_aggregator — malformed judge state -> judicial_fallback; else chief_justice
    builder.add_conditional_edges(
        "judge_aggregator",
        route_after_judge_aggregator,
    )

    # Error paths rejoin at chief_justice
    builder.add_edge("skip_judges", "chief_justice")
    builder.add_edge("judicial_fallback", "chief_justice")
    builder.add_edge("chief_justice", END)

    return builder.compile()


def get_initial_state(repo_url: str, pdf_path: str) -> dict:
    """Build initial state with rubric dimensions for running the full graph."""
    return {
        "repo_url": repo_url,
        "pdf_path": pdf_path or "",
        "rubric_dimensions": _load_rubric_dimensions(),
        "evidences": {},
        "opinions": [],
        "final_report": None,
    }
