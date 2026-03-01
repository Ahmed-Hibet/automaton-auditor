"""
Detective layer: RepoInvestigator and DocAnalyst as LangGraph nodes.
They output structured Evidence objects only; no opinionation.
"""

import json
import tempfile
from pathlib import Path
from typing import Any

from src.state import AgentState, Evidence
from src.tools.repo_tools import (
    clone_repo,
    extract_git_history,
    analyze_graph_structure,
    analyze_state_management,
    check_sandboxed_tools,
)
from src.tools.doc_tools import (
    ingest_pdf,
    query_pdf_chunks,
    extract_file_paths_from_text,
    extract_images_from_pdf,
)


def _repo_dimensions(state: AgentState) -> list[dict]:
    dims = state.get("rubric_dimensions") or []
    return [d for d in dims if d.get("target_artifact") == "github_repo"]


def _pdf_dimensions(state: AgentState) -> list[dict]:
    dims = state.get("rubric_dimensions") or []
    return [d for d in dims if d.get("target_artifact") == "pdf_report"]


def _evidence(
    goal: str,
    found: bool,
    location: str,
    rationale: str,
    confidence: float,
    content: str | None = None,
) -> Evidence:
    return Evidence(
        goal=goal,
        found=found,
        content=content,
        location=location,
        rationale=rationale,
        confidence=confidence,
    )


def repo_investigator_node(state: AgentState) -> dict[str, Any]:
    """
    RepoInvestigator: clone repo in sandbox, run git log + AST analysis,
    produce Evidence per rubric dimension targeting github_repo.
    """
    repo_url = state.get("repo_url") or ""
    dimensions = _repo_dimensions(state)
    evidences: list[Evidence] = []
    if not repo_url:
        evidences.append(
            _evidence(
                goal="repo_access",
                found=False,
                location="",
                rationale="No repo_url provided in state.",
                confidence=0.0,
            )
        )
        return {"evidences": {"repo_investigator": evidences}}

    try:
        with tempfile.TemporaryDirectory() as tmp:
            clone_path = clone_repo(repo_url, tmp)
            root = Path(clone_path)

            # Git forensic analysis
            dim = next((d for d in dimensions if d.get("id") == "git_forensic_analysis"), None)
            if dim:
                history = extract_git_history(clone_path)
                count = len(history)
                progression = count > 3 and any(
                    "setup" in str(h.get("subject", "")).lower()
                    or "tool" in str(h.get("subject", "")).lower()
                    or "graph" in str(h.get("subject", "")).lower()
                    for h in history
                )
                found = count > 0
                evidences.append(
                    _evidence(
                        goal=dim["name"],
                        found=found,
                        location=clone_path,
                        rationale=f"git log --oneline --reverse: {count} commits. Progression story: {progression}. Entries: {json.dumps(history[:20])}",
                        confidence=0.9 if found else 0.0,
                        content=json.dumps(history[:30], indent=2),
                    )
                )

            # State management rigor
            dim = next((d for d in dimensions if d.get("id") == "state_management_rigor"), None)
            if dim:
                res = analyze_state_management(clone_path)
                ok = res.get("has_pydantic") and res.get("has_evidence") and res.get("has_judicial_opinion") and res.get("has_reducers")
                evidences.append(
                    _evidence(
                        goal=dim["name"],
                        found=res.get("found", False),
                        location=res.get("path", ""),
                        rationale=f"AST: Pydantic={res.get('has_pydantic')}, Evidence={res.get('has_evidence')}, JudicialOpinion={res.get('has_judicial_opinion')}, reducers add/ior={res.get('has_reducers')}.",
                        confidence=0.95 if ok else 0.3,
                        content=res.get("code_snippet"),
                    )
                )

            # Graph orchestration
            dim = next((d for d in dimensions if d.get("id") == "graph_orchestration"), None)
            if dim:
                res = analyze_graph_structure(clone_path)
                ok = res.get("has_state_graph") and (res.get("parallel_fan_out") or res.get("add_edge_count", 0) >= 2) and res.get("synchronization_node")
                evidences.append(
                    _evidence(
                        goal=dim["name"],
                        found=res.get("found", False),
                        location=res.get("path", ""),
                        rationale=f"StateGraph={res.get('has_state_graph')}, parallel_fan_out={res.get('parallel_fan_out')}, sync_node={res.get('synchronization_node')}, edges={len(res.get('edges', []))}.",
                        confidence=0.9 if ok else 0.4,
                        content=res.get("code_snippet"),
                    )
                )

            # Safe tool engineering
            dim = next((d for d in dimensions if d.get("id") == "safe_tool_engineering"), None)
            if dim:
                res = check_sandboxed_tools(clone_path)
                ok = res.get("uses_tempfile") and res.get("uses_subprocess") and not res.get("raw_os_system")
                evidences.append(
                    _evidence(
                        goal=dim["name"],
                        found=res.get("found", False),
                        location=res.get("path", ""),
                        rationale=f"tempfile={res.get('uses_tempfile')}, subprocess={res.get('uses_subprocess')}, raw os.system={res.get('raw_os_system')}.",
                        confidence=0.95 if ok else (0.2 if res.get("raw_os_system") else 0.5),
                        content=res.get("clone_function_snippet"),
                    )
                )

    except Exception as e:
        evidences.append(
            _evidence(
                goal="repo_investigator",
                found=False,
                location=repo_url,
                rationale=f"Error: {e!s}",
                confidence=0.0,
            )
        )

    return {"evidences": {"repo_investigator": evidences}}


def doc_analyst_node(state: AgentState) -> dict[str, Any]:
    """
    DocAnalyst: ingest PDF, run RAG-lite queries for theoretical depth and
    report accuracy (cross-reference paths). Output Evidence per pdf_report dimension.
    """
    pdf_path = state.get("pdf_path") or ""
    dimensions = _pdf_dimensions(state)
    evidences: list[Evidence] = []

    if not pdf_path:
        evidences.append(
            _evidence(
                goal="pdf_ingest",
                found=False,
                location="",
                rationale="No pdf_path provided in state.",
                confidence=0.0,
            )
        )
        return {"evidences": {"doc_analyst": evidences}}

    ingest = ingest_pdf(pdf_path)
    if not ingest.get("ok"):
        evidences.append(
            _evidence(
                goal="pdf_ingest",
                found=False,
                location=pdf_path,
                rationale=ingest.get("error", "Ingest failed"),
                confidence=0.0,
            )
        )
        return {"evidences": {"doc_analyst": evidences}}

    full_text = ""
    for c in ingest.get("chunks", []):
        full_text += c + "\n\n"

    # Theoretical depth
    dim = next((d for d in dimensions if d.get("id") == "theoretical_depth"), None)
    if dim:
        q = query_pdf_chunks(ingest, "Dialectical Synthesis Fan-In Fan-Out Metacognition State Synchronization")
        matches = q.get("matches", [])
        found = len(matches) > 0
        rationale = f"RAG-lite matches: {len(matches)}. Terms searched in chunked PDF."
        evidences.append(
            _evidence(
                goal=dim["name"],
                found=found,
                location=pdf_path,
                rationale=rationale,
                confidence=min(0.9, 0.3 + 0.1 * len(matches)),
                content="\n---\n".join((m.get("chunk", "")[:500] for m in matches[:5])),
            )
        )

    # Report accuracy: extract file paths from PDF text for cross-reference
    dim = next((d for d in dimensions if d.get("id") == "report_accuracy"), None)
    if dim:
        paths_mentioned = extract_file_paths_from_text(full_text)
        evidences.append(
            _evidence(
                goal=dim["name"],
                found=len(paths_mentioned) >= 0,
                location=pdf_path,
                rationale=f"Extracted file paths mentioned in report: {paths_mentioned}. Cross-reference with RepoInvestigator evidence to verify.",
                confidence=0.7,
                content=json.dumps(paths_mentioned),
            )
        )

    return {"evidences": {"doc_analyst": evidences}}


def vision_inspector_node(state: AgentState) -> dict[str, Any]:
    """
    VisionInspector (Diagram Detective): extract images from PDF, optionally run
    vision model. Per challenge: implementation required, execution optional.
    Returns Evidence for swarm_visual dimension; if no images or no vision API, returns
    minimal evidence (e.g. "no images extracted" or "vision analysis skipped").
    """
    pdf_path = state.get("pdf_path") or ""
    dimensions = state.get("rubric_dimensions") or []
    pdf_image_dims = [d for d in dimensions if d.get("target_artifact") == "pdf_images"]
    evidences: list[Evidence] = []

    if not pdf_path:
        evidences.append(
            _evidence(
                goal="swarm_visual",
                found=False,
                location="",
                rationale="No pdf_path provided; VisionInspector skipped.",
                confidence=0.0,
            )
        )
        return {"evidences": {"vision_inspector": evidences}}

    result = extract_images_from_pdf(pdf_path)
    if not result.get("ok"):
        evidences.append(
            _evidence(
                goal="Architectural Diagram Analysis",
                found=False,
                location=pdf_path,
                rationale=result.get("error", "Image extraction failed"),
                confidence=0.0,
            )
        )
        return {"evidences": {"vision_inspector": evidences}}

    count = result.get("count", 0)
    if count == 0:
        evidences.append(
            _evidence(
                goal="Architectural Diagram Analysis",
                found=False,
                location=pdf_path,
                rationale="No images extracted from PDF (optional vision execution not run).",
                confidence=0.5,
            )
        )
    else:
        evidences.append(
            _evidence(
                goal="Architectural Diagram Analysis",
                found=True,
                location=pdf_path,
                rationale=f"Extracted {count} image(s) from PDF. Vision model analysis is optional per rubric; diagram classification can be run with Gemini/GPT-4o if configured.",
                confidence=0.7,
                content=json.dumps([{"page": im.get("page")} for im in result.get("images", [])]),
            )
        )
    # Clean up temp image files if paths were returned
    for im in result.get("images", []):
        p = im.get("path")
        if p and isinstance(p, str):
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
    return {"evidences": {"vision_inspector": evidences}}


def evidence_aggregator_node(state: AgentState) -> dict[str, Any]:
    """
    Fan-in: collect all evidence from parallel detectives. No new evidence;
    just passes state through so the graph can route to Judges (or end for interim).
    """
    return {}
