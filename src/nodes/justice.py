"""
Chief Justice synthesis: hardcoded deterministic conflict resolution.
Consumes JudicialOpinions from Prosecutor, Defense, Tech Lead and produces AuditReport.
"""

from collections import defaultdict
from typing import Any

from src.state import (
    AgentState,
    AuditReport,
    CriterionResult,
    JudicialOpinion,
)


def _load_synthesis_rules() -> dict[str, str]:
    """Load synthesis_rules from rubric config if available."""
    import json
    from pathlib import Path
    paths = [
        Path(__file__).resolve().parent.parent.parent / "config" / "rubric.json",
        Path("config/rubric.json"),
    ]
    for p in paths:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data.get("synthesis_rules", {})
            except Exception:
                pass
    return {}


def _resolve_score(
    opinions: list[JudicialOpinion],
    dimension_id: str,
    dimension_name: str,
    evidences: dict,
) -> tuple[int, str | None, str]:
    """
    Hardcoded deterministic resolution. Returns (final_score, dissent_summary, remediation).
    Rules: Security override (cap 3), Fact supremacy, Functionality weight, variance > 2 -> dissent.
    """
    by_judge = {o.judge: o for o in opinions}
    prosecutor = by_judge.get("Prosecutor")
    defense = by_judge.get("Defense")
    tech_lead = by_judge.get("TechLead")
    scores = [o.score for o in opinions if o is not None]
    if not scores:
        return 3, None, "No opinions available for this criterion."

    # Rule of Security: Prosecutor flags security -> cap at 3
    security_terms = ("security", "os.system", "injection", "sanitiz", "unsafe")
    if prosecutor and any(
        t in (prosecutor.argument or "").lower() for t in security_terms
    ):
        final = min(3, max(scores))
        dissent = "Prosecutor identified security concerns; score capped at 3 per Rule of Security."
        remediation = "Address security issues in tooling (sandboxing, no raw os.system, input validation)."
        return final, dissent, remediation

    # Rule of Functionality: for graph/architecture criterion, Tech Lead carries highest weight
    arch_criteria = ("graph_orchestration", "state_management_rigor", "safe_tool_engineering")
    if dimension_id in arch_criteria and tech_lead:
        final = tech_lead.score
        if len(scores) >= 2 and (max(scores) - min(scores)) > 2:
            dissent = f"Prosecutor: {prosecutor.score if prosecutor else '?'}, Defense: {defense.score if defense else '?'}, Tech Lead: {tech_lead.score}. Tech Lead weight applied (Rule of Functionality)."
        else:
            dissent = None
        remediation = "Follow rubric success patterns for this dimension; see forensic evidence for gaps."
        return final, dissent, remediation

    # Default: median of three, or average; require dissent when variance > 2
    variance = max(scores) - min(scores) if len(scores) >= 2 else 0
    if variance > 2:
        # Use Tech Lead as tie-breaker when available, else middle value
        if tech_lead:
            final = tech_lead.score
        else:
            final = sorted(scores)[len(scores) // 2]
        dissent = " ".join(
            f"{o.judge}={o.score}" for o in opinions
        ) + ". Variance > 2; dissent recorded."
        remediation = "Review conflicting judge opinions and address gaps cited by Prosecutor; strengthen evidence for Defense claims."
    else:
        final = round(sum(scores) / len(scores))
        final = max(1, min(5, final))
        dissent = None
        remediation = "Address any cited gaps to improve score."

    return final, dissent, remediation


def _build_criterion_results(
    state: AgentState,
) -> list[CriterionResult]:
    """Group opinions by criterion_id and resolve each to CriterionResult."""
    opinions: list[JudicialOpinion] = list(state.get("opinions") or [])
    dimensions = state.get("rubric_dimensions") or []
    evidences = state.get("evidences") or {}
    by_criterion: dict[str, list[JudicialOpinion]] = defaultdict(list)
    for op in opinions:
        by_criterion[op.criterion_id].append(op)

    results: list[CriterionResult] = []
    for dim in dimensions:
        dim_id = dim.get("id", "")
        dim_name = dim.get("name", "Unknown")
        ops = by_criterion.get(dim_id, [])
        score, dissent, remediation = _resolve_score(
            ops, dim_id, dim_name, evidences
        )
        results.append(
            CriterionResult(
                dimension_id=dim_id,
                dimension_name=dim_name,
                final_score=score,
                judge_opinions=ops,
                dissent_summary=dissent,
                remediation=remediation,
            )
        )
    return results


def chief_justice_node(state: AgentState) -> dict[str, Any]:
    """
    Synthesis engine: deterministic resolution of judge opinions into AuditReport.
    Output is stored in state.final_report and can be serialized to Markdown.
    If judicial_skip_reason is set (error-path routing), it is included in the executive summary.
    """
    repo_url = state.get("repo_url") or ""
    skip_reason = state.get("judicial_skip_reason")
    criteria = _build_criterion_results(state)
    if not criteria:
        summary = "No rubric dimensions or opinions available."
        if skip_reason:
            summary = f"{skip_reason} {summary}"
        report = AuditReport(
            repo_url=repo_url,
            executive_summary=summary,
            overall_score=0.0,
            criteria=[],
            remediation_plan="Run the full graph with rubric and judges.",
        )
        return {"final_report": report}

    overall = sum(c.final_score for c in criteria) / len(criteria)
    summary_parts = [
        f"Audit of {repo_url}. Overall score: {overall:.1f}/5.",
        f"Criteria assessed: {len(criteria)}.",
    ]
    if skip_reason:
        summary_parts.insert(0, f"[Note: {skip_reason}]")
    remediation_parts = [c.remediation for c in criteria if c.remediation]
    report = AuditReport(
        repo_url=repo_url,
        executive_summary=" ".join(summary_parts),
        overall_score=round(overall, 1),
        criteria=criteria,
        remediation_plan=" ".join(remediation_parts) if remediation_parts else "See per-criterion remediation.",
    )
    return {"final_report": report}


def audit_report_to_markdown(report: AuditReport) -> str:
    """Serialize AuditReport to Markdown (Executive Summary, Criterion Breakdown, Remediation Plan)."""
    lines = [
        "# Automaton Auditor — Audit Report",
        "",
        f"**Repository:** {report.repo_url}",
        "",
        "## Executive Summary",
        "",
        report.executive_summary,
        "",
        f"**Overall Score:** {report.overall_score}/5",
        "",
        "---",
        "",
        "## Criterion Breakdown",
        "",
    ]
    for c in report.criteria:
        lines.append(f"### {c.dimension_name} (`{c.dimension_id}`)")
        lines.append("")
        lines.append(f"**Final Score:** {c.final_score}/5")
        lines.append("")
        for op in c.judge_opinions:
            lines.append(f"- **{op.judge}:** {op.score}/5 — {op.argument[:200]}{'...' if len(op.argument or '') > 200 else ''}")
        if c.dissent_summary:
            lines.append("")
            lines.append("**Dissent:** " + c.dissent_summary)
        lines.append("")
        lines.append("**Remediation:** " + c.remediation)
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Remediation Plan")
    lines.append("")
    lines.append(report.remediation_plan)
    lines.append("")
    return "\n".join(lines)
