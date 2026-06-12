# -*- coding: utf-8 -*-
"""Batch-evaluate every factor in a library: translate each with AI, run it with
the project's real operators, compute IC, and print a table sorted by |IC|.

Example:
  python batch_ic.py --factors ".../gtja191/factors.py" --helpers ".../research_core" \
      --data "clean.parquet" --project-root "...agentmatrix-research-main" \
      --module-path "research_core.factor_lab.libraries.gtja191.factors" [--hold 5] [--only _alpha1,_alpha2]
"""
from __future__ import annotations
import os
import sys
import ast
import argparse
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from core import scanner, dependency, translator, static_check, executor, evaluator
from llm import client


def factor_func_names(factors_path):
    """Top-level function names defined in the factors FILE, in source order."""
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            src = open(factors_path, encoding=enc).read(); break
        except Exception:
            src = None
    if src is None:
        return []
    return [n.name for n in ast.parse(src).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def main():
    p = argparse.ArgumentParser(prog="batch_ic")
    p.add_argument("--factors", required=True); p.add_argument("--helpers")
    p.add_argument("--data", required=True); p.add_argument("--hold", type=int, default=5)
    p.add_argument("--project-root"); p.add_argument("--module-path")
    p.add_argument("--provider"); p.add_argument("--only", help="comma-separated names")
    a = p.parse_args()

    if not client.available():
        print("No API key configured. Set $env:DEEPSEEK_API_KEY first."); return

    index = scanner.scan_paths([x for x in [a.factors, a.helpers] if x])["index"]
    names = factor_func_names(a.factors)
    if a.only:
        wanted = set(s.strip() for s in a.only.split(","))
        names = [n for n in names if n in wanted]

    df = pd.read_parquet(a.data) if a.data.endswith(".parquet") else pd.read_csv(a.data)
    df["date"] = pd.to_datetime(df["date"]); df["code"] = df["code"].astype(str)
    df = df.sort_values(["code", "date"]).reset_index(drop=True)

    rows, skipped = [], []
    for name in names:
        if name not in index:
            skipped.append((name, "not scanned")); continue
        rec = index[name]
        deps, _ = dependency.trace(name, index)
        ref = dependency.reference_text(name, index, deps)
        try:
            tr = translator.translate(name, rec["source"], ref, provider=a.provider)
        except Exception as e:
            skipped.append((name, f"translate error: {e}")); continue
        if tr.get("sentinel"):
            skipped.append((name, tr["sentinel"])); continue
        code = tr["final_code"]
        chk = static_check.check(code, rec["source"], set(deps))
        if chk["status"] in ("compile_failed", "missing_compute_factor"):
            skipped.append((name, chk["status"])); continue
        try:
            factor = executor.run(code, dependency.helper_sources(index, deps), df,
                project_roots=[a.project_root] if a.project_root else None,
                module_path=a.module_path)
            ev = evaluator.evaluate(df, factor, hold_days=a.hold)
        except Exception as e:
            skipped.append((name, f"run error: {type(e).__name__}: {e}")); continue
        rows.append({"factor": name, "IC": ev["ic"]["mean"], "t": ev["ic"]["t_stat"],
                     "RankIC": ev["rank_ic"]["mean"], "LS%": ev["ls_total_return"]*100,
                     "evidence": ev["evidence"], "monotonic": ev["monotonic"]})
        print(f"  done {name}: IC {ev['ic']['mean']:+.4f} (t={ev['ic']['t_stat']:+.2f}) "
              f"{ev['evidence']}")

    if rows:
        res = pd.DataFrame(rows)
        res["absIC"] = res["IC"].abs()
        res = res.sort_values("absIC", ascending=False).drop(columns="absIC")
        print("\n========== Batch IC (sorted by |IC|) ==========")
        print(res.to_string(index=False,
              formatters={"IC": "{:+.4f}".format, "t": "{:+.2f}".format,
                          "RankIC": "{:+.4f}".format, "LS%": "{:+.1f}".format}))
    if skipped:
        print("\nSkipped (not factors / errors):")
        for n, why in skipped:
            print(f"  {n}: {why}")


if __name__ == "__main__":
    main()
