"""
Run the Automaton Auditor detective graph (interim: no judges).
Usage: uv run python main.py --repo-url <url> [--pdf-path <path>]
"""

import argparse

from dotenv import load_dotenv

from src.graph import build_graph, get_initial_state

# Load .env so API keys (OPENAI, LANGCHAIN) are never hardcoded (rubric: project infrastructure)
load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Run detective graph against a repo (and optional PDF).")
    parser.add_argument("--repo-url", required=True, help="GitHub repository URL to audit")
    parser.add_argument("--pdf-path", default="", help="Path to PDF report (optional)")
    args = parser.parse_args()

    graph = build_graph()
    state = get_initial_state(repo_url=args.repo_url, pdf_path=args.pdf_path or "")

    result = graph.invoke(state)

    evidences = result.get("evidences") or {}
    print("Evidence keys:", list(evidences.keys()))
    for source, items in evidences.items():
        print(f"\n--- {source} ({len(items)} items) ---")
        for i, ev in enumerate(items):
            if hasattr(ev, "model_dump"):
                ev = ev.model_dump()
            print(f"  [{i+1}] goal={ev.get('goal')} found={ev.get('found')} confidence={ev.get('confidence')}")
            print(f"      rationale: {str(ev.get('rationale', ''))[:200]}...")
    print("\nDone. Set LANGCHAIN_TRACING_V2=true for LangSmith traces.")


if __name__ == "__main__":
    main()
