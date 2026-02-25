"""
Doc forensic tools: PDF ingestion and RAG-lite chunked querying.
Avoids dumping the whole PDF into context; chunks and allows targeted queries.
"""

import re
from pathlib import Path
from typing import Any

# Optional: use pypdf for lightweight extraction (no Docling/PyTorch)
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None  # type: ignore[misc, assignment]


CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks for RAG-lite retrieval."""
    if not text or not text.strip():
        return []
    chunks = []
    start = 0
    text = text.replace("\r\n", "\n")
    while start < len(text):
        end = start + size
        chunk = text[start:end]
        if not chunk.strip():
            start = end - overlap
            continue
        chunks.append(chunk.strip())
        start = end - overlap
    return chunks


def ingest_pdf(pdf_path: str) -> dict[str, Any]:
    """
    Ingest PDF: extract text and build chunked index for querying.
    Returns { "ok": bool, "chunks": [...], "full_text_length": int, "error": optional }.
    """
    if PdfReader is None:
        return {
            "ok": False,
            "chunks": [],
            "full_text_length": 0,
            "error": "pypdf not installed. Add pypdf to pyproject.toml and run uv sync.",
        }
    path = Path(pdf_path)
    if not path.exists():
        return {
            "ok": False,
            "chunks": [],
            "full_text_length": 0,
            "error": f"File not found: {pdf_path}",
        }
    try:
        reader = PdfReader(str(path))
        parts = []
        for page in reader.pages:
            try:
                t = page.extract_text()
                if t:
                    parts.append(t)
            except Exception:
                continue
        full_text = "\n\n".join(parts)
        chunks = _chunk_text(full_text)
        return {
            "ok": True,
            "chunks": chunks,
            "full_text_length": len(full_text),
            "num_pages": len(reader.pages),
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "chunks": [],
            "full_text_length": 0,
            "error": str(e),
        }


def query_pdf_chunks(ingest_result: dict[str, Any], query: str) -> dict[str, Any]:
    """
    RAG-lite: find chunks that contain query terms or are relevant.
    Returns { "matches": [{"chunk": str, "score": float}], "query": str }.
    """
    if not ingest_result.get("ok") or not ingest_result.get("chunks"):
        return {
            "matches": [],
            "query": query,
            "error": ingest_result.get("error", "No chunks available"),
        }
    chunks = ingest_result["chunks"]
    query_lower = query.lower()
    terms = re.findall(r"\w+", query_lower)
    scored = []
    for i, chunk in enumerate(chunks):
        chunk_lower = chunk.lower()
        score = 0.0
        for t in terms:
            if t in chunk_lower:
                score += 1.0
                # bonus for multiple occurrences
                score += 0.2 * (chunk_lower.count(t) - 1)
        if score > 0:
            scored.append((score, i, chunk))
    scored.sort(key=lambda x: -x[0])
    matches = [{"chunk": c, "score": s, "index": i} for s, i, c in scored[:15]]
    return {
        "matches": matches,
        "query": query,
        "error": None,
    }


def extract_file_paths_from_text(text: str) -> list[str]:
    """
    Extract file paths mentioned in report text (e.g. src/tools/ast_parser.py)
    for cross-reference with RepoInvestigator.
    """
    # Common patterns: src/..., path/to/file.py, "src/state.py"
    pattern = re.compile(
        r"(?:src/[\w./-]+\.(?:py|json|md|toml)|[\w]+/[\w./-]+\.(?:py|json|md|toml))"
    )
    found = set()
    for m in pattern.finditer(text):
        found.add(m.group(0))
    return sorted(found)
