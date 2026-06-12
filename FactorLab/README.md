# Factor Reproduction Studio

A small desktop app (and CLI) for AI-assisted factor reproduction: point it at an
external factor library, it scans the candidate factors and their helper/operator
definitions, asks an LLM to translate **one** factor into a runnable
`compute_factor(df)` **strictly from the source** (no guessing), runs a simple
backtest on your data, and produces a clean HTML report with four charts.

No factor database, no truth verification, no release workflow — just
scan → translate → check → backtest → report.

## Install

```bash
pip install -r requirements.txt
```

## Use the desktop app

```bash
python main.py
```

1. **API settings** — paste your DeepSeek key (OpenAI/Anthropic optional), Save, Test.
2. **Import files** — drag in the factor library `.py` (or folder), the
   operator/helper files (or project folder), and a data file (`.csv`/`.parquet`).
3. **Data** — check the column mapping, click *Convert and save standard data*.
4. **Factor scanner** — *Scan*, then click a factor to see its dependency tree.
5. **Translation** — *Translate with AI*, review/edit the code, *Run static check*.
6. **Backtest & report** — set holding days, *Run*, then *Open HTML report*.

If no API key is set, the Translation page tells you so — you can still paste a
`compute_factor(df)` by hand into the editor and run the backtest.

## Use the CLI (fully tested, no GUI needed)

```bash
# 1) list candidate factors + traced helpers
python cli.py scan --factors sample/factor_library.py --helpers sample/operators.py

# 2a) full run with AI translation (needs a key in config.local.json)
python cli.py run --factors sample/factor_library.py --helpers sample/operators.py \
    --data sample/demo.parquet --factor _alpha6 --hold 5

# 2b) run with a hand-written translation (no API key)
python cli.py run --factors sample/factor_library.py --helpers sample/operators.py \
    --data sample/demo.parquet --factor _alpha6 --code-file my_code.py
```

A working sample is included (`sample/factor_library.py`, `sample/operators.py`,
`sample/demo.parquet`).

## How the "no guessing" part works

1. **AST scan** finds every top-level function and classifies it (factor / helper
   / data) by structure and naming — not by asking the AI.
2. **Dependency tracing** walks each factor's calls recursively and collects the
   *exact source* of every helper it uses.
3. The LLM is given only that source + strict rules (don't guess, don't add
   preprocessing, don't change windows/direction, return one `compute_factor(df)`)
   and must emit `MISSING_HELPER` / `MISSING_FIELD` / `NOT_A_FACTOR` instead of
   inventing.
4. **Static checks** then compile the code, confirm `compute_factor` exists, and
   flag any call names that aren't among the provided helpers (catches the
   classic "AI hallucinated an operator" error).
5. Execution injects the real helper sources into the namespace, so the
   translated factor calls the project's own operators.

## Metrics

Coverage, IC / RankIC (mean, std, IR, t-stat, win rate), ICIR / RankICIR,
5-quantile group returns, long-short cumulative curve + max drawdown, and an
evidence level (Strong / Medium / Weak by |IC t-stat|). The backtest uses a
simple overlapping forward-return window — fine for a demo, not a production
backtester.

## Config / keys

Keys live in `config.local.json` (git-ignored) or environment variables
(`DEEPSEEK_API_KEY`, etc.). Nothing is hardcoded. DeepSeek is the default and
enough for the MVP; OpenAI/Anthropic are optional.

## Files

```
main.py            desktop app entry
cli.py             command-line entry (Phase-1 core, fully runnable)
core/scanner.py    AST scan + factor/helper classification
core/dependency.py recursive helper tracing + reference text + tree
core/translator.py build prompt, call LLM, parse response
core/static_check.py compile / compute_factor / suspicious-name checks
core/executor.py   run translated code with project helpers injected
core/data_standardizer.py column mapping -> standard long panel
core/evaluator.py  IC/RankIC/ICIR/groups/long-short/drawdown
core/report.py     polished HTML report + 4 charts (+ optional PDF)
llm/client.py      DeepSeek / OpenAI / Anthropic, local config
llm/prompts.py     strict translation prompt + parser
app/gui.py         PySide6 desktop UI wrapping the core
sample/            example factor library, operators, demo data
```
