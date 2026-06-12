# -*- coding: utf-8 -*-
"""Static checks on AI-translated code before running it."""
from __future__ import annotations
import ast

# names that are always fine in translated code
_ALLOWED_BASE = {
    "compute_factor", "df", "data", "np", "numpy", "pd", "pandas",
    "groupby", "rolling", "shift", "rank", "mean", "std", "sum", "min", "max",
    "corr", "cov", "apply", "transform", "pct_change", "diff", "abs", "sign",
    "log", "sqrt", "where", "fillna", "reset_index", "assign", "values",
    "index", "Series", "DataFrame", "astype", "len", "range", "float", "int", "copy", "dropna", "cumprod", "cumsum", "cummax", "ffill", "bfill", "clip", "rolling", "expanding", "ewm", "isna", "notna", "replace", "sort_values", "rename", "loc", "iloc", "to_numpy", "tolist", "nunique", "unique", "count", "median", "var", "skew", "kurt", "quantile", "first", "last", "head", "tail", "merge", "concat", "pivot", "stack", "unstack",
    "round", "zip", "list", "dict", "tuple", "set", "sorted", "map", "enumerate",
}


def check(translated_code: str, factor_source: str, helper_names: set[str]) -> dict:
    issues = []

    # 1. compile
    try:
        tree = ast.parse(translated_code)
    except SyntaxError as e:
        return {"status": "compile_failed", "issues": [f"SyntaxError: {e}"]}

    # 2. compute_factor present with one arg
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    if "compute_factor" not in funcs:
        return {"status": "missing_compute_factor",
                "issues": ["No function compute_factor(df) defined."]}

    # 3. suspicious-name check: function calls that are neither helpers, allowed
    #    base names, nor defined in the translated code itself.
    defined = set(funcs)
    called = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                called.add(f.id)
            elif isinstance(f, ast.Attribute):
                called.add(f.attr)
    known = _ALLOWED_BASE | helper_names | defined
    suspicious = sorted(c for c in called if c not in known and not c.startswith("_"))
    # only flag if it looks like an undefined helper-style call
    suspicious = [s for s in suspicious if s.isidentifier() and len(s) > 2]
    if suspicious:
        issues.append("Calls names not found among helpers/allowed: "
                      + ", ".join(suspicious[:12]))

    status = "need_review" if issues else "passed"
    return {"status": status, "issues": issues, "suspicious": suspicious}
