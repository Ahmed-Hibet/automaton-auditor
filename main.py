"""
Run the full Automaton Auditor swarm: Detectives -> EvidenceAggregator -> Judicial Panel -> Chief Justice.
Output: state with final_report; optionally write Markdown to audit/.
Usage: uv run python main.py --repo-url <url> [--pdf-path <path>] [--output <path>]
"""

import argparse
from pathlib import Path

from dotenv import load_dotenv

from src.graph import build_graph, get_initial_state
from src.nodes.justice import audit_report_to_markdown

# Load .env so API keys (OPENAI, LANGCHAIN) are never hardcoded (rubric: project infrastructure)
load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="Run the Automaton Auditor swarm against a repo (and optional PDF report)."
    )
    parser.add_argument("--repo-url", required=True, help="GitHub repository URL to audit")
    parser.add_argument("--pdf-path", default="", help="Path to PDF report (optional)")
    parser.add_argument(
        "--output",
        default="",
        help="Write Markdown report to this path (default: audit/report_<slug>.md)",
    )
    parser.add_argument(
        "--detective-only",
        action="store_true",
        help="Run only detective layer (no judges/chief justice); print evidence only",
    )
    args = parser.parse_args()

    if args.detective_only:
        # Build minimal graph: detectives + evidence_aggregator only
        from langgraph.graph import START, END, StateGraph
        from src.state import AgentState
        from src.nodes.detectives import (
            repo_investigator_node,
            doc_analyst_node,
            vision_inspector_node,
            evidence_aggregator_node,
        )
        import json
        from pathlib import Path as P

        def _load():
            for p in [P(__file__).resolve().parent / "config" / "rubric.json", P("config/rubric.json")]:
                if p.exists():
                    try:
                        return json.loads(p.read_text(encoding="utf-8")).get("dimensions", [])
                    except Exception:
                        pass
            return []

        builder = StateGraph(AgentState)
        builder.add_node("repo_investigator", repo_investigator_node)
        builder.add_node("doc_analyst", doc_analyst_node)
        builder.add_node("vision_inspector", vision_inspector_node)
        builder.add_node("evidence_aggregator", evidence_aggregator_node)
        builder.add_conditional_edges(START, lambda _: ["repo_investigator", "doc_analyst", "vision_inspector"])
        builder.add_edge("repo_investigator", "evidence_aggregator")
        builder.add_edge("doc_analyst", "evidence_aggregator")
        builder.add_edge("vision_inspector", "evidence_aggregator")
        builder.add_edge("evidence_aggregator", END)
        graph = builder.compile()
        state = {
            "repo_url": args.repo_url,
            "pdf_path": args.pdf_path or "",
            "rubric_dimensions": _load(),
            "evidences": {},
            "opinions": [],
            "final_report": None,
        }
        result = graph.invoke(state)
        evidences = result.get("evidences") or {}
        print("Evidence keys:", list(evidences.keys()))
        for source, items in evidences.items():
            print(f"\n--- {source} ({len(items)} items) ---")
            for i, ev in enumerate(items):
                d = ev.model_dump() if hasattr(ev, "model_dump") else ev
                print(f"  [{i+1}] goal={d.get('goal')} found={d.get('found')} confidence={d.get('confidence')}")
                print(f"      rationale: {str(d.get('rationale', ''))[:200]}...")
        print("\nDone (detective-only).")
        return

    graph = build_graph()
    state = get_initial_state(repo_url=args.repo_url, pdf_path=args.pdf_path or "")
    result = graph.invoke(state)

    final_report = result.get("final_report")
    if final_report:
        md = audit_report_to_markdown(final_report)
        out_path = args.output
        if not out_path:
            slug = args.repo_url.rstrip("/").split("/")[-1].replace(".git", "") or "report"
            audit_dir = Path("audit")
            audit_dir.mkdir(parents=True, exist_ok=True)
            out_path = audit_dir / f"report_{slug}.md"
        else:
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"Report written to {out_path}")
    else:
        print("No final report in state (judges may have been skipped if OPENAI_API_KEY was missing).")
        evidences = result.get("evidences") or {}
        print("Evidence keys:", list(evidences.keys()))

    print("Done. Set LANGCHAIN_TRACING_V2=true for LangSmith traces.")


if __name__ == "__main__":
    main()
