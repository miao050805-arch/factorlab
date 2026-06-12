# -*- coding: utf-8 -*-
"""Drive one factor translation: build the strict prompt, call the LLM, and
parse the structured response. The prompt is stored for debugging."""
from __future__ import annotations
from llm import client, prompts


def translate(factor_name: str, factor_source: str, operator_reference: str,
              provider: str = None, cfg: dict = None) -> dict:
    prompt = prompts.build_prompt(factor_name, factor_source, operator_reference)
    raw = client.chat(prompt, system=prompts.SYSTEM, provider=provider,
                      temperature=0.0, cfg=cfg)
    parsed = prompts.parse_response(raw)
    parsed["prompt"] = prompt
    parsed["factor_name"] = factor_name
    return parsed
