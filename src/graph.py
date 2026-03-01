"""
Full StateGraph: Detectives (parallel) -> EvidenceAggregator -> Judicial Panel -> Chief Justice -> END.
Fan-out: RepoInvestigator, DocAnalyst, VisionInspector run in parallel.
Fan-in: EvidenceAggregator collects evidence, then Judicial Panel (Prosecutor, Defense, Tech Lead)
runs, then Chief Justice synthesizes the final AuditReport.
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
from src.nodes.judges import judicial_panel_node
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
    # Layer 2: Judicial
    builder.add_node("judicial_panel", judicial_panel_node)
    # Layer 3: Synthesis
    builder.add_node("chief_justice", chief_justice_node)

    # Fan-out: run all three detectives in parallel from START
    builder.add_conditional_edges(
        START,
        lambda _: ["repo_investigator", "doc_analyst", "vision_inspector"],
    )

    # Fan-in: all detectives feed into EvidenceAggregator
    builder.add_edge("repo_investigator", "evidence_aggregator")
    builder.add_edge("doc_analyst", "evidence_aggregator")
    builder.add_edge("vision_inspector", "evidence_aggregator")

    # EvidenceAggregator -> Judicial Panel -> Chief Justice -> END
    builder.add_edge("evidence_aggregator", "judicial_panel")
    builder.add_edge("judicial_panel", "chief_justice")
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
