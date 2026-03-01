# Automaton Auditor — Week 2 (Full)

Automated quality assurance swarm for auditing Week 2 repositories: **Detectives** (Repo, Doc, Vision) collect evidence in parallel → **EvidenceAggregator** (fan-in) → **Judicial Panel** (Prosecutor, Defense, Tech Lead) → **Chief Justice** synthesizes a final Audit Report (Markdown).

## Project infrastructure (rubric)

- **Package manager:** [uv](https://docs.astral.sh/uv/). Run `uv sync` to install from `pyproject.toml` and use the locked `uv.lock`.
- **Environment:** API keys are not hardcoded. Copy `.env.example` to `.env` and set your keys; the app loads `.env` via `python-dotenv`.
- **Observability:** Set `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY` in `.env` for LangSmith tracing.

## Setup

- **Python:** 3.11+
- **Package manager:** [uv](https://docs.astral.sh/uv/)

### Install dependencies

```bash
uv sync
```

### Environment variables

Copy `.env.example` to `.env` and set values (do not commit `.env`):

```bash
cp .env.example .env
```

Required:

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Used by the Judicial Panel (Prosecutor, Defense, Tech Lead). Required for full audit. |
| `LANGCHAIN_API_KEY` | LangSmith tracing |
| `LANGCHAIN_TRACING_V2` | Set to `true` to enable tracing |
| `LANGCHAIN_PROJECT` | e.g. `automaton-auditor` |

## How to run

### Full swarm (detectives + judges + chief justice → Markdown report)

```bash
uv run python main.py --repo-url "https://github.com/owner/repo" --pdf-path "path/to/report.pdf"
```

- **`--repo-url`** (required): GitHub repository URL to audit.
- **`--pdf-path`** (optional): Path to the PDF report. If omitted, DocAnalyst and VisionInspector return minimal evidence.
- **`--output`** (optional): Path where the Markdown report is written. Default: `audit/report_<repo_slug>.md`.

Example (audit this repo and a local PDF):

```bash
uv run python main.py --repo-url "https://github.com/your-org/automaton-auditor" --pdf-path "reports/interim_report.pdf"
```

Example with custom output path:

```bash
uv run python main.py --repo-url "https://github.com/owner/repo" --pdf-path "reports/final_report.pdf" --output "audit/report_onself_generated/audit.md"
```

If `OPENAI_API_KEY` is not set, the judicial panel is skipped and no `final_report` is produced; only evidence is collected.

### Detective-only (no judges, no report)

To run only the detective layer (RepoInvestigator, DocAnalyst, VisionInspector) and print evidence:

```bash
uv run python main.py --repo-url "https://github.com/owner/repo" --pdf-path "path/to/report.pdf" --detective-only
```

## Repository layout

| Path | Description |
|------|-------------|
| `src/state.py` | Pydantic/TypedDict state (Evidence, JudicialOpinion, CriterionResult, AuditReport, AgentState) with reducers |
| `src/tools/repo_tools.py` | Sandboxed git clone, git log, AST-based graph/state/sandbox analysis |
| `src/tools/doc_tools.py` | PDF ingestion, chunked querying (RAG-lite), image extraction for VisionInspector |
| `src/nodes/detectives.py` | RepoInvestigator, DocAnalyst, VisionInspector, EvidenceAggregator |
| `src/nodes/judges.py` | Judicial panel (Prosecutor, Defense, Tech Lead) with structured output |
| `src/nodes/justice.py` | Chief Justice synthesis and `audit_report_to_markdown()` |
| `src/graph.py` | Full StateGraph: detectives (parallel) → EvidenceAggregator → Judicial Panel → Chief Justice |
| `config/rubric.json` | Rubric dimensions and synthesis rules |
| `pyproject.toml` / `uv.lock` | Dependencies (uv) |
| `.env.example` | Required env vars (no secrets) |
| `audit/` | Output directory for generated Markdown reports |

## Audit report folders (deliverables)

- **`audit/report_onself_generated/`** — Report from running your agent against your own repo.
- **`audit/report_onpeer_generated/`** — Report from running your agent against a peer’s repo.
- **`audit/report_bypeer_received/`** — Report produced by a peer’s agent when auditing your repo.

Generate reports into these by using `--output audit/report_onself_generated/audit.md` (and similarly for the others).

## Reports

- **Interim:** `reports/interim_report.html` (convert to PDF if required).
- **Final:** Place your final PDF in `reports/final_report.pdf` so peers’ agents can access it.
