# -*- coding: utf-8 -*-
"""Generic AST scanner for ANY factor library.

Principles:
  - No hardcoded library. No alpha-only rule. No fixed helper names.
  - Every top-level function in the FIRST (factor) input is a candidate.
  - The SECOND (helper) input is used only for dependency tracing.
  - Each function gets a unique_name with a library prefix, e.g. gtja191_alpha001,
    wq101_alpha001, so factors from different libraries don't collide.
"""
from __future__ import annotations
import os
import re
import ast
from pathlib import Path

IGNORE_DIRS = {"__pycache__", ".git", ".venv", "venv", "env", "site-packages",
               ".mypy_cache", ".pytest_cache", "node_modules", ".idea", ".vscode",
               "outputs", "output", "cache", ".cache"}
ENCODINGS = ("utf-8", "utf-8-sig", "gbk")


def _read(path):
    for enc in ENCODINGS:
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            return None
    return None


def _safe(value):
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(value).strip()).strip("._")
    return value or "library"


def _library_prefix(paths):
    valid = [p for p in paths if p]
    if not valid:
        return "library"
    first = Path(valid[0]).resolve()
    if first.is_file():
        if first.stem.lower() in {"factor", "factors", "alpha", "alphas"}:
            return _safe(first.parent.name).lower()
        return _safe(first.stem).lower()
    return _safe(first.name).lower()


def _display_name(name):
    """_alpha1 -> alpha001, alpha_1 -> alpha001, my_factor -> my_factor."""
    stripped = str(name).strip().lstrip("_")
    m = re.match(r"(?i)^alpha_?(\d+)$", stripped)
    if m:
        return f"alpha{int(m.group(1)):03d}"
    return _safe(stripped)


def _calls_names_fields(node):
    calls, names, fields = set(), set(), set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                calls.add(f.id)
            elif isinstance(f, ast.Attribute):
                calls.add(f.attr)
        elif isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            v = n.value.strip()
            if v:
                fields.add(v)
    return sorted(calls), sorted(names), sorted(fields)


def _collect_py_files(paths):
    files = []
    for p in paths:
        if not p:
            continue
        p = str(p)
        if os.path.isdir(p):
            for root, dirs, fnames in os.walk(p):
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
                for fn in fnames:
                    if fn.endswith(".py"):
                        files.append(os.path.abspath(os.path.join(root, fn)))
        elif os.path.isfile(p) and p.endswith(".py"):
            files.append(os.path.abspath(p))
    return sorted(set(files))


def scan_paths(paths, **kwargs):
    """Scan files/folders -> {index, unique_index, flat}.
    Extra kwargs (use_cache, progress_callback, etc.) are accepted and ignored
    for compatibility with any GUI version."""
    prefix = _library_prefix(paths)
    files = _collect_py_files(paths)
    index, unique_index, flat = {}, {}, []
    for fp in files:
        src = _read(fp)
        if src is None:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        lines = src.splitlines()
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            calls, names, fields = _calls_names_fields(node)
            rec = {
                "name": node.name,
                "unique_name": f"{_safe(prefix)}_{_display_name(node.name)}",
                "file": os.path.abspath(fp), "start_line": start, "end_line": end,
                "source": "\n".join(lines[start - 1:end]),
                "args": [a.arg for a in node.args.args],
                "calls": calls, "names": names, "fields": fields, "kind": "function",
            }
            index[node.name] = rec
            unique_index[rec["unique_name"]] = rec
            flat.append(rec)
    return {"index": index, "unique_index": unique_index, "flat": flat,
            "cache_info": {"library_prefix": prefix, "files_total": len(files)}}


def classify(rec):
    return "function"
