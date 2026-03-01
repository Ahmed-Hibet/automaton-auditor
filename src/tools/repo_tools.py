"""
Forensic repo tools: sandboxed clone, git history, AST-based graph/state analysis.
No regex for structure checks; uses Python's ast module for irrefutable evidence.
"""

import ast
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

# Safe URL pattern for basic validation (allow https only for clone)
HTTPS_GIT_URL_PATTERN = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+(/.*)?$")


def _sanitize_repo_url(url: str) -> str:
    """Strip .git suffix and whitespace; do not allow arbitrary shell input."""
    u = url.strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    return u


def clone_repo(repo_url: str, target_dir: str) -> str:
    """
    Clone a GitHub repo into target_dir using subprocess. Caller must use
    tempfile.TemporaryDirectory() as target_dir to sandbox. No os.system.
    Returns path to cloned repo (target_dir / repo_name).
    """
    url = _sanitize_repo_url(repo_url)
    if not HTTPS_GIT_URL_PATTERN.match(url):
        raise ValueError(f"Unsupported or invalid repo URL: {repo_url}")
    # Ensure URL has scheme for clone
    clone_url = url if url.startswith("http") else f"https://github.com/{url}"
    if "/" in clone_url.rstrip("/").split("github.com/")[-1]:
        repo_name = clone_url.rstrip("/").split("/")[-1]
    else:
        repo_name = clone_url.rstrip("/").split("/")[-1] or "repo"
    dest = Path(target_dir) / repo_name
    result = subprocess.run(
        ["git", "clone", "--depth", "50", clone_url, str(dest)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=target_dir,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"git clone failed: {err}")
    return str(dest)


def extract_git_history(repo_path: str) -> list[dict[str, Any]]:
    """
    Run git log --oneline --reverse with timestamps. Returns list of
    {commit_hash, subject, timestamp} for forensic analysis.
    """
    path = Path(repo_path)
    if not (path / ".git").exists():
        return []
    result = subprocess.run(
        ["git", "log", "--oneline", "--reverse", "--format=%h %s %ci"],
        capture_output=True,
        text=True,
        cwd=str(path),
        timeout=30,
    )
    if result.returncode != 0:
        return []
    entries = []
    for line in (result.stdout or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # format: "abc1234 subject 2024-01-15 12:00:00 +0000"
        parts = line.split(" ", 2)
        if len(parts) >= 3:
            entries.append(
                {
                    "commit_hash": parts[0],
                    "subject": parts[1],
                    "timestamp": parts[2],
                }
            )
        elif len(parts) == 2:
            entries.append(
                {"commit_hash": parts[0], "subject": parts[1], "timestamp": ""}
            )
    return entries


def _find_python_files(root: Path, *names: str) -> Optional[Path]:
    for name in names:
        p = root / name
        if p.exists() and p.suffix == ".py":
            return p
    return None


def analyze_graph_structure(repo_path: str) -> dict[str, Any]:
    """
    Use AST to verify StateGraph usage and edge structure (fan-out/fan-in).
    Returns structured evidence: has_state_graph, edges, parallel_fan_out, etc.
    """
    root = Path(repo_path)
    graph_file = root / "src" / "graph.py"
    if not graph_file.exists():
        graph_file = _find_python_files(root, "graph.py", "src/graph.py")
    if not graph_file or not graph_file.exists():
        return {
            "found": False,
            "path": str(graph_file) if graph_file else "src/graph.py",
            "has_state_graph": False,
            "edges": [],
            "parallel_fan_out": False,
            "synchronization_node": None,
            "code_snippet": None,
            "error": "graph file not found",
        }
    try:
        text = graph_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except SyntaxError as e:
        return {
            "found": True,
            "path": str(graph_file),
            "has_state_graph": False,
            "edges": [],
            "parallel_fan_out": False,
            "synchronization_node": None,
            "code_snippet": None,
            "error": str(e),
        }
    edges = []
    has_builder = False
    add_edge_calls = []
    add_conditional_calls = []
    node_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if attr == "add_edge":
                    add_edge_calls.append(node)
                elif attr == "add_conditional_edges":
                    add_conditional_calls.append(node)
            if isinstance(node.func, ast.Name):
                if node.func.id == "StateGraph":
                    has_builder = True
        if isinstance(node, (ast.FunctionDef, ast.Assign)):
            for n in ast.walk(node):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                    if n.func.attr == "add_node":
                        if n.args and isinstance(n.args[0], ast.Constant):
                            node_names.add(str(n.args[0].value))
    for call in add_edge_calls:
        if len(call.args) >= 2:
            src = ast.unparse(call.args[0]) if hasattr(ast, "unparse") else _unparse_simple(call.args[0])
            tgt = ast.unparse(call.args[1]) if hasattr(ast, "unparse") else _unparse_simple(call.args[1])
            edges.append({"source": src, "target": tgt, "type": "edge"})
    for call in add_conditional_calls:
        if call.args:
            src = ast.unparse(call.args[0]) if hasattr(ast, "unparse") else _unparse_simple(call.args[0])
            edges.append({"source": src, "target": "<conditional>", "type": "conditional"})
    # Heuristic: multiple edges from same source -> fan-out; node named *aggregat* -> fan-in
    sources = [e["source"] for e in edges]
    from collections import Counter
    source_counts = Counter(sources)
    parallel_fan_out = any(c >= 2 for c in source_counts.values())
    sync_node = None
    for n in node_names:
        if "aggregat" in n.lower() or "sync" in n.lower() or "collect" in n.lower():
            sync_node = n
            break
    return {
        "found": True,
        "path": str(graph_file),
        "has_state_graph": has_builder,
        "edges": edges,
        "add_edge_count": len(add_edge_calls),
        "add_conditional_count": len(add_conditional_calls),
        "parallel_fan_out": parallel_fan_out,
        "synchronization_node": sync_node,
        "node_names": list(node_names),
        "code_snippet": text[:3000] if len(text) > 3000 else text,
        "error": None,
    }


def _unparse_simple(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ast.dump(node)


def analyze_state_management(repo_path: str) -> dict[str, Any]:
    """
    AST-based check for state.py or graph.py: BaseModel, TypedDict,
    Evidence, JudicialOpinion, AgentState, and reducers (operator.add, operator.ior).
    """
    root = Path(repo_path)
    state_file = root / "src" / "state.py"
    if not state_file.exists():
        state_file = _find_python_files(root, "state.py")
    if not state_file or not state_file.exists():
        return {
            "found": False,
            "path": "src/state.py",
            "has_pydantic": False,
            "has_typed_dict": False,
            "has_evidence": False,
            "has_judicial_opinion": False,
            "has_reducers": False,
            "code_snippet": None,
            "error": "state file not found",
        }
    try:
        text = state_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except SyntaxError as e:
        return {
            "found": True,
            "path": str(state_file),
            "has_pydantic": False,
            "has_typed_dict": False,
            "has_evidence": False,
            "has_judicial_opinion": False,
            "has_reducers": False,
            "code_snippet": None,
            "error": str(e),
        }
    has_base_model = False
    has_typed_dict = False
    has_evidence = False
    has_judicial = False
    has_operator_add = False
    has_operator_ior = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if node.name == "Evidence":
                has_evidence = True
            if node.name == "JudicialOpinion":
                has_judicial = True
            if node.name == "AgentState":
                for st in ast.walk(node):
                    if isinstance(st, ast.Attribute):
                        if getattr(st, "attr", None) == "add":
                            has_operator_add = True
                        if getattr(st, "attr", None) == "ior":
                            has_operator_ior = True
            for base in node.bases:
                name = getattr(base, "id", None)
                if isinstance(base, ast.Attribute):
                    name = base.attr
                if name == "BaseModel":
                    has_base_model = True
                if name == "TypedDict":
                    has_typed_dict = True
        if isinstance(node, ast.Attribute):
            if node.attr == "add":
                has_operator_add = True
            if node.attr == "ior":
                has_operator_ior = True
    has_reducers = has_operator_add and has_operator_ior
    return {
        "found": True,
        "path": str(state_file),
        "has_pydantic": has_base_model,
        "has_typed_dict": has_typed_dict,
        "has_evidence": has_evidence,
        "has_judicial_opinion": has_judicial,
        "has_reducers": has_reducers,
        "code_snippet": text[:2500] if len(text) > 2500 else text,
        "error": None,
    }


def check_sandboxed_tools(repo_path: str) -> dict[str, Any]:
    """
    Scan src/tools for sandboxing (tempfile.TemporaryDirectory),
    absence of raw os.system, and use of subprocess with error handling.
    """
    root = Path(repo_path)
    tools_dir = root / "src" / "tools"
    if not tools_dir.exists():
        return {
            "found": False,
            "path": str(tools_dir),
            "uses_tempfile": False,
            "uses_subprocess": False,
            "raw_os_system": None,
            "clone_function_snippet": None,
            "error": "src/tools not found",
        }
    uses_tempfile = False
    uses_subprocess = False
    raw_os_system = []
    clone_snippet = None
    for py in tools_dir.glob("*.py"):
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
            if "TemporaryDirectory" in text or "tempfile" in text:
                uses_tempfile = True
            if "subprocess" in text and ("run" in text or "Popen" in text):
                uses_subprocess = True
            if "os.system" in text:
                raw_os_system.append(str(py))
            if "clone" in text.lower() and "def " in text:
                clone_snippet = text[:2000]
        except Exception:
            continue
    return {
        "found": True,
        "path": str(tools_dir),
        "uses_tempfile": uses_tempfile,
        "uses_subprocess": uses_subprocess,
        "raw_os_system": raw_os_system if raw_os_system else None,
        "clone_function_snippet": clone_snippet,
        "error": None,
    }
