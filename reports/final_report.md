# Final Report: The Automaton Auditor

**Week 2 — TRP1 Challenge: Orchestrating Deep LangGraph Swarms for Autonomous Governance**

---

## 1. Executive Summary

This report documents the **final implementation** of the Automaton Auditor: a hierarchical LangGraph swarm that audits Week 2 repositories and their PDF reports. The system implements the full “Digital Courtroom”: **Layer 1** (Detectives: RepoInvestigator, DocAnalyst, VisionInspector) collect forensic evidence in parallel; **Layer 2** (Judicial Panel: Prosecutor, Defense, Tech Lead) produce structured opinions per rubric criterion; **Layer 3** (Chief Justice) applies hardcoded conflict-resolution rules and outputs a Markdown audit report.

Deliverables are in place: typed state with reducers, sandboxed repo tools with AST-based analysis, PDF ingestion and image extraction, three judge personas with `.with_structured_output(JudicialOpinion)`, Chief Justice synthesis with Rule of Security, Fact Supremacy, and Functionality weight, and end-to-end graph from repo URL + PDF to written report. Remaining gaps (e.g. conditional edges for “Evidence Missing”, optional vision-model analysis of diagrams) are documented with a remediation plan.

---

## 2. Architecture Deep Dive

### 2.1 Dialectical Synthesis (Thesis–Antithesis–Synthesis)

**What it is:** The rubric requires a *dialectical* process: not a single “grader” but three distinct viewpoints that argue over the same evidence, with a final synthesis that resolves conflict.

**How we implement it:**

- **Thesis / Antithesis:** Three judge personas in `src/nodes/judges.py` each receive the *same* evidence summary (from `_evidence_summary_for_judges`) and the same rubric dimensions. They differ only by system prompt:
  - **Prosecutor:** “Trust No One. Assume Vibe Coding.” — scrutinizes gaps, security, laziness; argues for low scores when requirements are unmet.
  - **Defense:** “Reward Effort and Intent. Look for the Spirit of the Law.” — highlights effort, Git history, and architectural intent even when implementation is imperfect.
  - **Tech Lead:** “Does it actually work? Is it maintainable?” — tie-breaker; focuses on artifacts, reducers, and safety; gives 1, 3, or 5 with remediation advice.

- **Synthesis:** `src/nodes/justice.py` implements **Chief Justice** as *deterministic Python logic*, not an LLM. It groups `state.opinions` by `criterion_id` and, for each criterion, applies:
  - **Rule of Security:** If the Prosecutor’s argument mentions security-related terms (e.g. `os.system`, injection), the score is capped at 3 regardless of Defense.
  - **Rule of Functionality:** For architecture-related criteria (`graph_orchestration`, `state_management_rigor`, `safe_tool_engineering`), the Tech Lead’s score is taken as the final score.
  - **Variance > 2:** If the three scores differ by more than 2, a dissent summary is written and the Tech Lead is used as tie-breaker (or median).

So “Dialectical Synthesis” is implemented by: (1) three independent opinions on the same evidence, (2) a fixed rule set that resolves conflict (security overrides effort, Tech Lead breaks ties and dominates on architecture), and (3) explicit dissent in the report when variance is high.

### 2.2 Fan-In / Fan-Out and State Synchronization

**Fan-out:** Multiple nodes are triggered from one point and run in parallel so that work is split without sequential bottlenecks.

**How we implement it:**

- **Detective fan-out:** In `src/graph.py`, `add_conditional_edges(START, lambda _: ["repo_investigator", "doc_analyst", "vision_inspector"])` causes all three detective nodes to be invoked from START. LangGraph runs these branches in parallel; each returns updates to `evidences` keyed by source (`repo_investigator`, `doc_analyst`, `vision_inspector`).

- **State merge (no overwrite):** `AgentState` in `src/state.py` declares `evidences` as `Annotated[Dict[str, List[Evidence]], operator.ior]`. The `operator.ior` reducer merges dicts (e.g. `dict_a | dict_b`), so each detective’s output is merged by key instead of overwriting. Similarly, `opinions` is `Annotated[List[JudicialOpinion], operator.add]`, so multiple judges (if we split them into separate graph nodes later) would append rather than replace.

**Fan-in:** All parallel branches must complete before the next stage uses their combined result.

- **Evidence aggregation:** The graph has a single **EvidenceAggregator** node. All three detectives have edges *into* it (`repo_investigator → evidence_aggregator`, `doc_analyst → evidence_aggregator`, `vision_inspector → evidence_aggregator`). LangGraph’s semantics ensure the aggregator runs only after all incoming edges have been updated; at that point `state.evidences` contains merged evidence from all three detectives.

- **Judicial panel:** The three judges are currently invoked *inside* one node (`judicial_panel_node`) in sequence (to keep one LLM call per persona and avoid rate limits). They all read the same aggregated evidence and append to `state.opinions` via the `operator.add` reducer. So conceptually we have “three views” fanning into one list, then Chief Justice runs once on that list.

**State synchronization** is thus: (1) fan-out from START to three detectives, (2) reducer `operator.ior` merges their `evidences`, (3) one aggregator node as sync point, (4) judicial panel produces `opinions` (reducer `operator.add`), (5) Chief Justice reads the full `opinions` and writes `final_report` once.

### 2.3 Metacognition

**What it is (in this context):** The system is not just “generating” code or text; it is *evaluating* artifacts (repo + report) against a rubric. That requires “thinking about thinking”: understanding what “good” means (success/failure patterns), distinguishing fact from opinion, and applying rules consistently.

**How we implement it:**

- **Constitution (rubric):** `config/rubric.json` holds the grading constitution: dimensions with `forensic_instruction`, `success_pattern`, and `failure_pattern`. Detectives are given only the dimensions whose `target_artifact` matches their role (repo vs PDF vs images). Judges receive the same dimensions plus evidence; they are prompted to score against these patterns. The Chief Justice does not re-interpret the rubric; it applies fixed rules (security, functionality, variance) to the numeric and textual output of the judges.

- **Fact vs. opinion:** Detectives output only **Evidence** (goal, found, location, rationale, confidence, content). They do not score. Scoring is done by the Judicial Panel, which *cites* evidence in `cited_evidence` and gives an argument. The Chief Justice then uses facts (e.g. “Prosecutor mentioned security”) to override or weight opinions. So the pipeline enforces: facts first (detectives), then interpretation (judges), then rule-based resolution (Chief Justice).

- **Self-evaluation:** Running the auditor against its own repo (and this report) is an instance of metacognition: the system’s design is documented and then assessed by the same rubric it uses to assess others. The final report (e.g. in `audit/report_onself_generated/`) is the tangible output of that self-audit.

---

## 3. Architectural Diagram: StateGraph Flow

The following diagram reflects the actual wiring in `src/graph.py`.

```
INPUT: AgentState { repo_url, pdf_path, rubric_dimensions, evidences={}, opinions=[], final_report=None }

                         ┌─────────────────────┐
                         │       START        │
                         └─────────┬──────────┘
                                   │
           ┌───────────────────────┼───────────────────────┐
           │                       │                       │
           ▼                       ▼                       ▼
  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
  │ RepoInvestigator│   │   DocAnalyst    │   │ VisionInspector │   ← Fan-out (parallel)
  │ (clone, git log,│   │ (ingest PDF,   │   │ (extract images │
  │  AST graph/state│   │  RAG query,     │   │  from PDF;      │
  │  sandbox check) │   │  path extract)  │   │  optional vision)│
  └────────┬────────┘   └────────┬───────┘   └────────┬────────┘
           │                      │                     │
           │ evidences            │ evidences           │ evidences
           │ (operator.ior merge) │                     │
           └──────────────────────┼─────────────────────┘
                                  ▼
                    ┌─────────────────────────┐
                    │   EvidenceAggregator   │   ← Fan-in (sync)
                    │   (pass-through; state  │
                    │    now has full         │
                    │    evidences)           │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   Judicial Panel       │
                    │   (Prosecutor, Defense, │
                    │    Tech Lead; each      │
                    │    returns opinions     │
                    │    via structured output)│
                    └────────────┬────────────┘
                                 │ opinions (operator.add)
                                 ▼
                    ┌─────────────────────────┐
                    │   Chief Justice         │
                    │   (hardcoded rules:      │
                    │    security, functionality,│
                    │    variance → dissent)   │
                    └────────────┬────────────┘
                                 │ final_report: AuditReport
                                 ▼
                                END
                                 │
                                 ▼
                    Output: Markdown file (audit/report_*.md)
```

**Data flow summary:**

- **Edges** carry the full `AgentState`; only the keys that a node updates are specified (e.g. `evidences`, `opinions`, `final_report`).
- **Reducers** ensure parallel nodes do not overwrite: `evidences` uses `operator.ior`, `opinions` uses `operator.add`.
- **Single writer:** Only the Chief Justice writes `final_report`; no reducer needed there.

---

## 4. Criterion-by-Criterion Self-Audit (Implementation vs. Rubric)

| Criterion | Implementation | Self-assessment |
|-----------|----------------|-----------------|
| **Git Forensic Analysis** | `repo_tools.extract_git_history()` runs `git log --oneline --reverse --format=%h %s %ci`; RepoInvestigator checks commit count and progression keywords. | Meets: git log extracted; progression story checked. |
| **State Management Rigor** | `state.py`: `Evidence`, `JudicialOpinion`, `CriterionResult`, `AuditReport` (Pydantic); `AgentState` (TypedDict) with `Annotated[…, operator.ior]` and `operator.add`. `repo_tools.analyze_state_management()` uses AST to find BaseModel/TypedDict, Evidence, JudicialOpinion, reducers. | Meets: typed state and reducers; AST verification. |
| **Graph Orchestration** | `graph.py`: StateGraph with conditional_edges from START to three detectives; edges into EvidenceAggregator; then judicial_panel → chief_justice → END. `analyze_graph_structure()` parses add_edge/add_conditional_edges and sync node names. | Meets: detective fan-out/fan-in; judicial panel and Chief Justice in graph. |
| **Safe Tool Engineering** | `clone_repo()` requires a target_dir (used with `tempfile.TemporaryDirectory()` in the node); `subprocess.run` for git; URL validated with HTTPS GitHub regex; no `os.system`. `check_sandboxed_tools()` scans for tempfile/subprocess and flags os.system. | Meets: sandboxed clone, subprocess, no os.system. |
| **Structured Output Enforcement** | Judges use `ChatOpenAI(...).with_structured_output(JudgeVerdict)`; JudgeVerdict contains list of opinions with criterion_id, score, argument, cited_evidence; converted to `JudicialOpinion` with judge name. Retry/fallback on failure returns default opinions. | Meets: Pydantic-bound LLM output; schema alignment. |
| **Judicial Nuance** | Prosecutor, Defense, Tech Lead have distinct system prompts (adversarial vs. forgiving vs. pragmatic). Same evidence and dimensions; different scores/arguments expected. | Meets: three personas; dialectical design. |
| **Chief Justice Synthesis** | `justice.py`: `_resolve_score()` implements Rule of Security (cap 3), Rule of Functionality (Tech Lead for arch criteria), variance > 2 → dissent and tie-break. Output is `AuditReport`; `audit_report_to_markdown()` produces Markdown. | Meets: deterministic rules; Markdown report. |
| **Theoretical Depth (Doc)** | DocAnalyst uses `query_pdf_chunks()` for terms like “Dialectical Synthesis”, “Metacognition”; evidence includes chunk excerpts. | Meets: RAG-lite over PDF; concept search. |
| **Report Accuracy** | `extract_file_paths_from_text()` pulls paths from PDF; evidence lists them for cross-check with RepoInvestigator. No automatic “verified vs hallucinated” list in report yet. | Partial: path extraction and evidence; cross-ref could be explicit in report. |
| **Swarm Visual (Diagram)** | VisionInspector: `extract_images_from_pdf()` in doc_tools; node returns Evidence for diagram dimension. Optional vision model not wired; implementation present, execution optional per rubric. | Meets: image extraction implemented; vision analysis optional. |

---

## 5. Reflection on the MinMax Feedback Loop

- **What a peer’s agent might catch:** (1) Missing conditional edges for “Evidence Missing” or “Node Failure” (graph always proceeds to judges). (2) Judicial panel runs three LLM calls in sequence, not as three separate graph nodes, so the “Judges fan-out” is conceptual rather than explicit in the graph. (3) Report Accuracy dimension could output an explicit “Verified vs. Hallucinated paths” section. (4) Vision model (e.g. GPT-4o/Gemini) not invoked for diagram classification.

- **How we could update the agent after peer feedback:** (1) Add conditional edge from EvidenceAggregator: if critical evidence is missing (e.g. repo clone failed), route to a “retry” or “fail_gracefully” node instead of judicial panel. (2) Optionally split judicial_panel into three graph nodes (Prosecutor, Defense, TechLead) with edges into a “judge_aggregator” so the rubric’s “Judges in parallel” is visible in the graph. (3) In Chief Justice or DocAnalyst, add a step that compares paths mentioned in the PDF to RepoInvestigator’s file list and writes “Verified paths” / “Hallucinated paths” into the report. (4) In VisionInspector, call a vision API on extracted images when available and add diagram-classification evidence.

---

## 6. Remediation Plan for Remaining Gaps

| Gap | Remediation |
|-----|-------------|
| No conditional edges for clone/PDF failure | Add a router after EvidenceAggregator: if `evidences` lacks repo_investigator success or critical keys, route to a “partial_report” or “error_report” node instead of judicial_panel; still produce a minimal AuditReport. |
| Judges implemented as one node | Optionally refactor to three nodes (prosecutor_node, defense_node, tech_lead_node) with edges to a single “judge_sync” node; keep using `operator.add` for opinions so Chief Justice sees all three. |
| Report Accuracy: no explicit verified/hallucinated list | In DocAnalyst or in a small post-step, intersect `extract_file_paths_from_text(pdf_text)` with file paths discovered by RepoInvestigator (e.g. from AST/path listing); write two lists into Evidence or into the final report section. |
| VisionInspector does not call vision model | Add optional branch in vision_inspector_node: if images exist and OPENAI_API_KEY (or VISION_API_KEY) is set, call GPT-4o or Gemini with image input and a prompt for “StateGraph diagram vs. linear pipeline”; append result to Evidence. |
| Remediation plan section repetitive when all criteria share same text | In `audit_report_to_markdown()`, deduplicate or summarize remediation bullets per criterion before concatenating into the report’s Remediation Plan section. |

---

## 7. Deliverables Checklist

- **Source:** `src/state.py`, `src/tools/repo_tools.py`, `src/tools/doc_tools.py`, `src/nodes/detectives.py`, `src/nodes/judges.py`, `src/nodes/justice.py`, `src/graph.py`, `main.py`, `config/rubric.json`, `pyproject.toml`, `.env.example`, `README.md`, optional `Dockerfile`.
- **Audit reports:** `audit/report_onself_generated/`, `audit/report_onpeer_generated/`, `audit/report_bypeer_received/` (run with `--output` to populate).
- **Final report:** This document (`reports/final_report.md`); can be converted to PDF for submission.
