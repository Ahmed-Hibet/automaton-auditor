"""
Partial StateGraph for Interim Submission: Detectives in parallel (fan-out)
with EvidenceAggregator (fan-in). Judges not required yet.
"""

import json
from pathlib import Path

from langgraph.graph import START, END, StateGraph

from src.state import AgentState
from src.nodes.detectives import (
    repo_investigator_node,
    doc_analyst_node,
    evidence_aggregator_node,
)


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

    builder.add_node("repo_investigator", repo_investigator_node)
    builder.add_node("doc_analyst", doc_analyst_node)
    builder.add_node("evidence_aggregator", evidence_aggregator_node)

    # Fan-out: run both detectives in parallel from START
    builder.add_conditional_edges(
        START,
        lambda _: ["repo_investigator", "doc_analyst"],
    )

    # Fan-in: both detectives feed into EvidenceAggregator
    builder.add_edge("repo_investigator", "evidence_aggregator")
    builder.add_edge("doc_analyst", "evidence_aggregator")

    builder.add_edge("evidence_aggregator", END)

    return builder.compile()


def get_initial_state(repo_url: str, pdf_path: str) -> dict:
    """Build initial state with rubric dimensions for running the detective graph."""
    return {
        "repo_url": repo_url,
        "pdf_path": pdf_path,
        "rubric_dimensions": _load_rubric_dimensions(),
        "evidences": {},
        "opinions": [],
        "final_report": None,
    }
