# -*- coding: utf-8 -*-
"""LLM client supporting DeepSeek (default), OpenAI, and Anthropic.

Keys are read from config.local.json (preferred, set via the GUI Settings page)
or environment variables. Nothing is hardcoded.
"""
from __future__ import annotations
import os
import json

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           "config.local.json")

DEFAULTS = {
    "provider": "deepseek",
    "deepseek_api_key": "", "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-chat",
    "openai_api_key": "", "openai_model": "gpt-4o-mini",
    "anthropic_api_key": "", "anthropic_model": "claude-3-5-sonnet-latest",
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            cfg.update(json.load(open(CONFIG_PATH, encoding="utf-8")))
        except Exception:
            pass
    # env fallback
    for prov in ("deepseek", "openai", "anthropic"):
        env = os.getenv(f"{prov.upper()}_API_KEY")
        if env and not cfg.get(f"{prov}_api_key"):
            cfg[f"{prov}_api_key"] = env
    return cfg


def save_config(cfg: dict):
    json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def available(cfg: dict = None) -> list[str]:
    cfg = cfg or load_config()
    return [p for p in ("deepseek", "openai", "anthropic")
            if cfg.get(f"{p}_api_key")]


def chat(prompt: str, system: str = "", provider: str = None,
         temperature: float = 0.0, cfg: dict = None) -> str:
    cfg = cfg or load_config()
    provider = provider or cfg.get("provider", "deepseek")
    key = cfg.get(f"{provider}_api_key", "")
    if not key:
        raise RuntimeError("AI translation unavailable. Please enter an API key "
                           "in Settings.")
    if provider in ("deepseek", "openai"):
        from openai import OpenAI
        base = cfg["deepseek_base_url"] if provider == "deepseek" else "https://api.openai.com/v1"
        model = cfg["deepseek_model"] if provider == "deepseek" else cfg["openai_model"]
        client = OpenAI(api_key=key, base_url=base)
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        r = client.chat.completions.create(model=model, messages=msgs,
                                           temperature=temperature, max_tokens=4000)
        return r.choices[0].message.content or ""
    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        r = client.messages.create(model=cfg["anthropic_model"], max_tokens=4000,
                                    temperature=temperature, system=system or "",
                                    messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    raise ValueError(f"Unknown provider: {provider}")


def test_key(provider: str, cfg: dict = None) -> tuple[bool, str]:
    try:
        out = chat("Reply with the single word: OK", provider=provider,
                   cfg=cfg, temperature=0.0)
        return True, out.strip()[:80]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
