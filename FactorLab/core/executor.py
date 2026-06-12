# -*- coding: utf-8 -*-
"""Execute the translated factor against a project's REAL operators.

If `module_path` is given (e.g. 'research_core.factor_lab.libraries.gtja191.factors'),
every function in that module is injected into the namespace, so the translated
code calls the project's own helpers with all real cross-file dependencies
intact. Otherwise the traced helper sources are spliced in (works for simple
single-file helper libraries).
"""
from __future__ import annotations
import os
import sys
import inspect
import importlib
import numpy as np
import pandas as pd


def run(translated_code, helper_source, df, project_roots=None, module_path=None):
    ns = {"np": np, "numpy": np, "pd": pd, "pandas": pd}
    added = []
    for root in (project_roots or []):
        for cand in (root, os.path.dirname(root.rstrip("/\\"))):
            if cand and os.path.isdir(cand) and cand not in sys.path:
                sys.path.insert(0, cand); added.append(cand)
    try:
        if module_path:
            mod = importlib.import_module(module_path)
            for name, obj in inspect.getmembers(mod, inspect.isfunction):
                ns[name] = obj
        elif helper_source.strip():
            exec(compile(helper_source, "<helpers>", "exec"), ns)
        exec(compile(translated_code, "<factor>", "exec"), ns)
        if "compute_factor" not in ns:
            raise ValueError("Translated code does not define compute_factor(df).")
        result = ns["compute_factor"](df.copy())
    finally:
        for r in added:
            try:
                sys.path.remove(r)
            except ValueError:
                pass
    if not isinstance(result, pd.Series):
        result = pd.Series(np.asarray(result, dtype="float64"))
    s = result.astype("float64")
    if len(s) != len(df):
        raise ValueError("Factor length %d != df length %d." % (len(s), len(df)))
    s.index = df.index
    return s
