# -*- coding: utf-8 -*-
"""Command-line entry. AI recommends the holding period when --hold is omitted.

Examples:
  python cli.py scan --factors lib.py --helpers ops/
  python cli.py run --factors lib.py --helpers ops/ --data d.parquet --factor _alpha6
      [--hold N] [--code-file f.py] [--project-root ROOT --module-path pkg.mod]
"""
from __future__ import annotations
import os
import re
import sys
import argparse
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from core import scanner, dependency, translator, static_check, executor, evaluator, report
from llm import client

OUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")


def _scan(factors, helpers):
    paths = [p for p in [factors, helpers] if p]
    return scanner.scan_paths(paths)["index"]


def recommend_hold(factor_source, provider=None):
    """Ask the LLM for a holding period (trading days). Falls back to 5."""
    if not client.available():
        return 5, "default (no LLM)"
    try:
        prompt = ("Given this quant factor code, recommend ONE holding period in "
                  "trading days as a single integer (short-term reversal 1-5, "
                  "momentum 5-20, mid-term 20-60, fundamental 60+). Reply with "
                  "ONLY the integer.\n\n" + factor_source)
        out = client.chat(prompt, provider=provider, temperature=0.0)
        n = int(re.search(r"\d+", out).group())
        return max(1, min(120, n)), "AI-recommended"
    except Exception:
        return 5, "default (AI failed)"


def cmd_scan(a):
    index = _scan(a.factors, a.helpers)
    factors = [r for r in index.values() if r["kind"] == "factor"]
    helpers = [r for r in index.values() if r["kind"] == "helper"]
    print("\nDiscovered %d candidate factor(s), %d helper(s):\n" % (len(factors), len(helpers)))
    for r in factors:
        deps, _ = dependency.trace(r["name"], index)
        print("  [factor] %-14s %s:%d-%d  fields=%s  helpers=%s" % (
            r["name"], os.path.basename(r["file"]), r["start_line"], r["end_line"],
            r["fields"], deps))
    print()
    for r in helpers:
        print("  [helper] %s" % r["name"])


def cmd_run(a):
    index = _scan(a.factors, a.helpers)
    if a.factor not in index:
        print("Factor '%s' not found. Run scan to list factors." % a.factor); return
    rec = index[a.factor]
    deps, edges = dependency.trace(a.factor, index)
    ref = dependency.reference_text(a.factor, index, deps)
    helper_src = dependency.helper_sources(index, deps)
    print("Dependency tree:"); print(dependency.ascii_tree(a.factor, edges), "\n")

    tr = {}
    if a.code_file:
        code = open(a.code_file, encoding="utf-8-sig").read()
        print("Using supplied translation from %s" % a.code_file)
    else:
        if not client.available():
            print("No API key configured. Provide --code-file or set a key."); return
        print("Translating with AI...")
        tr = translator.translate(a.factor, rec["source"], ref, provider=a.provider)
        if tr.get("sentinel"):
            print("AI returned:", tr["sentinel"]); return
        code = tr["final_code"]
        print("\n--- translated compute_factor ---\n", code, "\n")

    chk = static_check.check(code, rec["source"], set(deps))
    print("Static check:", chk["status"], chk.get("issues") or "")
    if chk["status"] in ("compile_failed", "missing_compute_factor"):
        return

    # holding period: user-specified, else AI-recommended, else default
    if a.hold is not None:
        hold, hold_src = a.hold, "user-specified"
    else:
        hold, hold_src = recommend_hold(rec["source"], a.provider)
    print("Holding period: %d days (%s)" % (hold, hold_src))

    df = pd.read_parquet(a.data) if a.data.endswith(".parquet") else pd.read_csv(a.data)
    df["date"] = pd.to_datetime(df["date"]); df["code"] = df["code"].astype(str)
    df = df.sort_values(["code", "date"]).reset_index(drop=True)

    factor = executor.run(code, helper_src, df,
        project_roots=[a.project_root] if a.project_root else None,
        module_path=a.module_path)
    ev = evaluator.evaluate(df, factor, hold_days=hold)
    print("\nCoverage %.1f%% | IC %.3f (t=%.2f) | RankIC %.3f | LS %.1f%% | Evidence %s" % (
        ev["coverage"]*100, ev["ic"]["mean"], ev["ic"]["t_stat"],
        ev["rank_ic"]["mean"], ev["ls_total_return"]*100, ev["evidence"]))
    path = report.generate(ev, tr, a.factor, code, chk["status"], OUT_DIR)
    print("Report:", path)


def main():
    p = argparse.ArgumentParser(prog="ai_factor_lab")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("--factors"); s.add_argument("--helpers")
    s.set_defaults(func=cmd_scan)
    r = sub.add_parser("run")
    r.add_argument("--factors", required=True); r.add_argument("--helpers")
    r.add_argument("--data", required=True); r.add_argument("--factor", required=True)
    r.add_argument("--hold", type=int, default=None); r.add_argument("--code-file")
    r.add_argument("--provider"); r.add_argument("--project-root"); r.add_argument("--module-path")
    r.set_defaults(func=cmd_run)
    a = p.parse_args(); a.func(a)


if __name__ == "__main__":
    main()
