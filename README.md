# Automaton Auditor — Week 2 Interim

Automated quality assurance swarm for auditing Week 2 repositories: forensic detectives (repo + doc) run in parallel, evidence is aggregated; judicial layer and synthesis engine are planned for the final submission.

## Project infrastructure (rubric)

- **Package manager:** Dependencies are managed with [uv](https://docs.astral.sh/uv/); run `uv sync` to install from `pyproject.toml` and use the locked `uv.lock`.
- **Environment isolation:** API keys and config are not hardcoded. Copy `.env.example` to `.env`, set your keys there; the app loads `.env` at startup via `python-dotenv` (see `main.py`). `.gitignore` excludes `.env` so secrets are never committed.
- **Observability:** Set `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY` in `.env` for LangSmith tracing of the graph run.

## Setup

- **Python**: 3.11+
- **Package manager**: [uv](https://docs.astral.sh/uv/)

### Install dependencies

```bash
uv sync
```

This installs from `pyproject.toml` and uses the locked `uv.lock` (managed via uv).

### Environment variables

Copy `.env.example` to `.env` and set values (do not commit `.env`):

```bash
cp .env.example .env
```

Required:

- `OPENAI_API_KEY` — used when Judges are added (optional for interim detective-only run)
- `LANGCHAIN_API_KEY` — for LangSmith tracing
- `LANGCHAIN_TRACING_V2=true` — enable tracing
- `LANGCHAIN_PROJECT=automaton-auditor` — LangSmith project name

## Run the detective graph

Interim graph: **RepoInvestigator** and **DocAnalyst** run in parallel (fan-out), then **EvidenceAggregator** (fan-in). No judges yet.

```bash
uv run python main.py --repo-url "https://github.com/owner/repo" --pdf-path "path/to/report.pdf"
```

If `--pdf-path` is omitted, only repo-based evidence is collected (DocAnalyst will return minimal evidence).

Example (audit this repo and a local PDF):

```bash
uv run python main.py --repo-url "https://github.com/your-org/automaton-auditor" --pdf-path "reports/interim_report.pdf"
```

Output: state with `evidences` populated by `repo_investigator` and `doc_analyst`; you can print or persist this for inspection.

## Repository layout (interim)

- `src/state.py` — Pydantic/TypedDict state (Evidence, JudicialOpinion, AgentState) with reducers (`operator.add`, `operator.ior`)
- `src/tools/repo_tools.py` — Sandboxed git clone (tempfile), git log, AST-based graph/state/sandbox analysis
- `src/tools/doc_tools.py` — PDF ingestion and chunked querying (RAG-lite)
- `src/nodes/detectives.py` — RepoInvestigator and DocAnalyst nodes outputting structured Evidence
- `src/graph.py` — StateGraph: detectives in parallel + EvidenceAggregator (fan-out/fan-in)
- `config/rubric.json` — Rubric dimensions and synthesis rules (constitution)
- `pyproject.toml` / `uv.lock` — Dependencies managed via uv
- `.env.example` — Required env vars (no secrets)
- `reports/interim_report.html` — Interim report (convert to PDF as needed)

## Reports

- **Interim**: `reports/interim_report.html` — Architecture decisions, known gaps, and planned StateGraph flow. Convert to PDF for submission if required.
