# -*- coding: utf-8 -*-
"""Mechanical factor extractor — NO AI rewriting of code.

Philosophy
----------
For libraries whose factors are already implemented as Python functions
(e.g. gtja191's ``_alpha8(df) -> pd.Series``), "translation" is purely
mechanical: rename the factor function to ``compute_factor`` and rely on the
traced helper sources for its dependencies. The original logic is preserved
byte-for-byte — no model ever rewrites, expands, optimizes, or reinterprets it.

The LLM is used ONLY (and optionally) to produce a plain-language explanation
for the human reviewer. It never writes or edits runnable code.

Drop this file in your project's ``core/`` package next to scanner.py /
dependency.py, i.e. ``core/extractor.py``.
"""
from __future__ import annotations
import ast
import re


# Names that are pandas/numpy/builtin and therefore NOT unresolved helpers.
_KNOWN_NAMES = {
    # builtins / common
    "abs", "min", "max", "len", "range", "float", "int", "str", "list", "tuple",
    "set", "dict", "sorted", "enumerate", "zip", "map", "any", "all", "sum",
    # numpy
    "np", "log", "sign", "sqrt", "exp", "where", "minimum", "maximum", "isnan",
    "nan", "inf", "full", "arange", "dot", "prod", "argmax", "argmin", "abs",
    "power", "clip", "nanmean", "nanstd",
    # pandas Series/DataFrame methods & constructors
    "pd", "Series", "DataFrame", "assign", "groupby", "transform", "apply",
    "rolling", "shift", "diff", "pct_change", "replace", "fillna", "where",
    "rank", "mean", "std", "sum", "min", "max", "cov", "corr", "sort_values",
    "reset_index", "to_numpy", "divide", "copy", "astype", "nunique", "abs",
    "iloc", "loc", "index", "columns", "values", "to_datetime", "concat",
}


def _rename_function(source: str, new_name: str = "compute_factor") -> str:
    """Rename the first top-level function in ``source`` to ``new_name``,
    preserving the body byte-for-byte (only the identifier on the def line
    changes). Returns source unchanged if it can't be parsed."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    func = next((n for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if func is None or func.name == new_name:
        return source
    lines = source.splitlines()
    idx = func.lineno - 1
    lines[idx] = re.sub(rf"(def\s+){re.escape(func.name)}\b",
                        rf"\g<1>{new_name}", lines[idx], count=1)
    return "\n".join(lines)


def unresolved_helpers(factor_rec: dict, index: dict) -> list[str]:
    """Best-effort list of called names that look like helpers but were NOT
    found in the scanned index. This is the honest version of dependency
    tracing: instead of silently dropping unknown calls, we surface them so a
    human can see something is missing before running."""
    out = []
    for name in factor_rec.get("calls", []):
        if name in index:
            continue
        if name in _KNOWN_NAMES:
            continue
        # heuristic: snake_case identifier, length > 2, not dunder
        if re.fullmatch(r"[a-z_][a-z0-9_]{2,}", name) and not name.startswith("__"):
            out.append(name)
    return sorted(set(out))


def extract(factor_rec: dict, helper_src: str) -> dict:
    """Produce a runnable ``compute_factor`` from an already-implemented factor.

    Returns a dict with:
      original_source : the factor function exactly as written
      final_code      : the factor renamed to compute_factor (fed to executor)
      bundle          : helper closure + compute_factor (standalone, for review)
      first_param     : name of the factor's first argument (usually 'df')
      factor_name     : unique/display name
    """
    src = factor_rec.get("source", "")
    final_code = _rename_function(src, "compute_factor")
    args = factor_rec.get("args", [])
    first_param = args[0] if args else "df"
    bundle = (helper_src.strip() + "\n\n\n" + final_code).strip() if helper_src else final_code
    return {
        "original_source": src,
        "final_code": final_code,
        "bundle": bundle,
        "first_param": first_param,
        "factor_name": factor_rec.get("unique_name", factor_rec.get("name", "")),
    }


# ---------------------------------------------------------------------------
# Optional AI: plain-language summary ONLY. Never writes runnable code.
# ---------------------------------------------------------------------------
SUMMARY_SYSTEM = (
    "You are a code-reading assistant. You explain what Python factor code does "
    "in plain language for a human reviewer. You NEVER rewrite, translate, "
    "optimize, refactor, or output code of any kind. You only describe what the "
    "given code already does, strictly based on what is written."
)

SUMMARY_TEMPLATE = """Explain, in plain language, exactly what the following quantitative factor code computes.

Rules:
- Describe it step by step, in the order the code executes.
- Refer to helper functions by name; state what each does based ONLY on the helper definitions provided below.
- Do NOT output any code, pseudocode, or formulas in code form.
- Do NOT suggest improvements or alternatives.
- Do NOT guess anything not present in the code.

Factor name: {factor_name}

Factor code (this is the ground truth — do not restate it as code):
{factor_source}

Helper / operator definitions (reference only):
{helper_src}

Now give a concise plain-language explanation in 5-10 sentences."""


def summarize(factor_rec: dict, helper_src: str, client_module,
              provider: str | None = None, cfg: dict | None = None) -> str:
    """Optional plain-language summary for human review. Code is never touched.
    ``client_module`` is your existing ``llm.client`` module."""
    prompt = SUMMARY_TEMPLATE.format(
        factor_name=factor_rec.get("unique_name", factor_rec.get("name", "")),
        factor_source=factor_rec.get("source", ""),
        helper_src=(helper_src or "(none)")[:12000],
    )
    return client_module.chat(prompt, system=SUMMARY_SYSTEM,
                              provider=provider, temperature=0.0, cfg=cfg)
