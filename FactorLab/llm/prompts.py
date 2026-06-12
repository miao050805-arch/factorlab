# -*- coding: utf-8 -*-
"""The strict translation prompt and the parser for the structured response."""
from __future__ import annotations
import re

SYSTEM = "You are a strict quantitative factor reproduction assistant. " \
         "You reproduce factor logic exactly from the provided source; you do " \
         "not guess, infer from finance knowledge, or add anything."

TEMPLATE = """You are a strict quantitative factor reproduction assistant.

Your task is to translate ONE original factor function into a runnable compute_factor(df) function.

You are not building a factor library. You are not designing a framework. You are
not optimizing the factor. You are only reproducing the original factor logic as
faithfully as possible.

Data structure:
- df is a long-format pandas DataFrame; each row is one stock on one date.
- The stock identifier column is "code"; the date column is "date".
- Time-series operations group by "code"; cross-sectional operations group by "date".
- The returned factor must be a pandas Series aligned with df.index.

Strict rules:
1. Do not guess missing function meanings.
2. Do not infer operator behavior from general finance knowledge.
3. Only use the helper/operator definitions provided below.
4. If a helper function is missing, output MISSING_HELPER and stop.
5. If a required field is missing, output MISSING_FIELD and stop.
6. If the original function is not a factor, output NOT_A_FACTOR and stop.
7-13. Do not add preprocessing, winsorization, neutralization, z-score, fillna, or clipping not present in the original code.
14-18. Do not change factor direction, window length, min_periods, ascending, or ddof. Do not convert long-format logic to wide-format.
19. Keep intermediate variables visible.
20. The final code must define exactly one function: compute_factor(df).
21. The final function must return a pandas Series aligned with df.index.

You may call the provided helper/operator functions directly by name; they are
available in the execution namespace, along with numpy as np and pandas as pd.

Required output format (use these exact section headers):

FACTOR_LOGIC:
<plain-language logic>

REQUIRED_FIELDS:
<list of df fields>

HELPERS_USED:
<list of helper/operator functions used>

DECOMPOSITION:
<step-by-step decomposition>

TRANSLATION_NOTES:
<uncertainty or assumptions>

FINAL_CODE:
<only python code, no markdown fences>

Original factor name:
{factor_name}

Original factor code:
{factor_source}

Available helper/operator definitions:
{operator_reference}

Now translate the original factor into compute_factor(df).
"""

SENTINELS = ("MISSING_HELPER", "MISSING_FIELD", "NOT_A_FACTOR")
_SECTIONS = ["FACTOR_LOGIC", "REQUIRED_FIELDS", "HELPERS_USED",
             "DECOMPOSITION", "TRANSLATION_NOTES", "FINAL_CODE"]


def build_prompt(factor_name, factor_source, operator_reference) -> str:
    return TEMPLATE.format(factor_name=factor_name, factor_source=factor_source,
                           operator_reference=operator_reference or "(none provided)")


def parse_response(text: str) -> dict:
    """Split the structured response into sections; extract FINAL_CODE cleanly."""
    for s in SENTINELS:
        if s in text[:200]:
            return {"sentinel": s, "raw": text}

    out = {"sentinel": None, "raw": text}
    # locate each header position
    positions = []
    for sec in _SECTIONS:
        m = re.search(rf"^{sec}\s*:?\s*$", text, re.M)
        if m:
            positions.append((m.start(), m.end(), sec))
    positions.sort()
    for i, (_, end, sec) in enumerate(positions):
        nxt = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        out[sec.lower()] = text[end:nxt].strip()

    code = out.get("final_code", "")
    code = _strip_fences(code)
    out["final_code"] = code
    return out


def _strip_fences(code: str) -> str:
    code = code.strip()
    if code.startswith("```"):
        code = code.split("\n", 1)[1] if "\n" in code else ""
        if code.rstrip().endswith("```"):
            code = code.rstrip()[:-3]
    return code.strip()
