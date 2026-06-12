# FactorLab

**AI-assisted factor reproduction and evaluation.**

中文简介：FactorLab 是一个 AI 辅助的因子复现与评估工具。用户提供外部因子库源码和对应的算子/helper 文件后，系统会先通过 Python AST 扫描函数、因子定义和依赖关系，尽可能找出每个因子实际调用的算子源码，再将这些上下文交给 LLM。LLM 的任务不是凭经验重写因子，而是严格依据源码上下文，将因子翻译成可运行的 `compute_factor(df)`。随后系统会在用户数据上执行因子计算，并生成 IC、Rank IC、分层收益、多空组合等基础评估报告。

FactorLab 的核心原则是：AI 不允许自由猜测。AST 层先提供明确的代码上下文，LLM 只能在这些上下文内进行翻译；如果缺少字段、缺少 helper，或者当前函数并不是因子，模型应当明确返回缺失信息，而不是自行补全逻辑。


You hand FactorLab an external factor library (e.g. WorldQuant-101 / GTJA-191 style)
plus the project that defines its operators. It scans the factors, traces the exact
operator/helper source each one depends on, asks an LLM to **translate the factor
strictly from that source** (no guessing, no added preprocessing), runs it against
your data using the project's *real* operators, and produces an IC / quantile /
long-short report.

The guiding principle: **the AI is not allowed to guess.** A Python AST layer finds
the precise code context first; the LLM only translates within that context.

---

## Why this exists

Public factor libraries are easy to find but hard to *run*: each `alphaNNN` calls
custom operators (`ts_rank`, `cross_sectional_rank`, `decay_linear`, ...) scattered
across multiple files, often with project-specific signatures. Copy-pasting one
factor rarely works. FactorLab automates "find the real operator definitions →
translate the factor faithfully → run and evaluate it."

---

## Features

- **Library-agnostic AST scanner** — every top-level function in the factor input is a
  candidate; no hardcoded `alphaNNN`-only rules. Each gets a library prefix
  (`gtja191_alpha001`, `wq101_alpha001`) so factors from different libraries don't collide.
- **Recursive dependency tracing** — collects the exact source of every operator a
  factor uses, plus an ASCII dependency tree.
- **Strict LLM translation** — the prompt forbids guessing, added winsorization /
  neutralization / fillna, and changing windows or direction. The model must emit
  `MISSING_HELPER` / `MISSING_FIELD` / `NOT_A_FACTOR` instead of inventing.
- **Static checks** — compile check, `compute_factor` presence, and a "hallucinated
  operator" check that flags calls to names not among the provided helpers.
- **Real-operator execution** — injects the project's actual operator module
  (`--module-path`) so cross-file dependencies and real signatures are preserved.
- **Data Doctor** — column auto-mapping (Chinese + English aliases), price/volume
  sanity cleaning, and **calendar-aligned extreme-value removal** that drops the
  fake 100%+ forward returns caused by suspension gaps.
- **Simple, honest backtest** — IC / RankIC / ICIR / t-stat, 5 quantile groups,
  long-short curve, max drawdown, evidence level.
- **Batch mode** — `batch_ic.py` evaluates every factor in a library and prints a
  table sorted by |IC|.
- **CLI + PySide6 GUI**, DeepSeek by default (OpenAI / Anthropic optional).

---

## Install

```bash
git clone https://github.com/<you>/factorlab.git
cd factorlab
pip install -r requirements.txt
```

Set an API key (key is never hardcoded):

```bash
export DEEPSEEK_API_KEY="sk-..."        # Linux/macOS
# or  $env:DEEPSEEK_API_KEY="sk-..."    # Windows PowerShell
# or paste it in the GUI's "API settings" page
```

---

## Quick start (CLI)

```bash
# 1. clean your raw data into a standard panel (auto-removes extreme/suspension fakes)
python -c "import sys; sys.path.insert(0,'.'); from core import data_doctor as d; \
  df,s=d.standardize_data('path/to/raw.parquet', output_path='data/clean_panel.parquet'); \
  d.print_summary(s)"

# 2. list the factors a library actually implements
python cli.py scan --factors path/to/lib/factors.py --helpers path/to/project

# 3. evaluate ALL factors and rank by |IC|
python batch_ic.py --factors path/to/lib/factors.py --helpers path/to/project \
  --data data/clean_panel.parquet --project-root path/to/project_root \
  --module-path your.module.path.to.factors --hold 5

# 4. full report for one factor (4 charts -> outputs/report_<name>.html)
python cli.py run --factors path/to/lib/factors.py --helpers path/to/project \
  --data data/clean_panel.parquet --factor <name> --project-root path/to/project_root \
  --module-path your.module.path.to.factors
```

A self-contained sample (`sample/`) lets you try the pipeline without a key:

```bash
python cli.py run --factors sample/factor_library.py --helpers sample/operators.py \
  --data sample/demo.parquet --factor _alpha6 --code-file your_compute_factor.py
```

## GUI

```bash
python main.py
```
Import files → Data (convert) → Factor scanner (scan & pick) → Translation
(translate & review) → Backtest & report. For real factors, fill **Project root**
and **Module path** on the Backtest page (same values as the CLI flags).

---

## How "no guessing" is enforced

1. The AST scanner identifies functions and their calls — not the AI.
2. The dependency tracer collects the **exact source** of every operator used.
3. The LLM receives only that source + strict rules, and must signal missing pieces
   rather than fabricate them.
4. Static checks reject code that calls operators which were never provided.
5. Execution uses the project's **real** operators, so a faithful translation runs
   exactly as the original would.

---

## Limitations (please read — this is not a finished/perfect tool)

This started as an internship demo and is deliberately simple. Known weaknesses:

- **The backtest is a screening tool, not a production backtester.** No transaction
  costs, no slippage, no liquidity/halt handling beyond extreme-value removal, no
  industry/size neutralization, equal-weighted quantiles only.
- **IC t-stats are optimistic.** IC is computed on every date (overlapping forward
  windows), so the daily IC observations are autocorrelated and the t-stat overstates
  significance. Treat evidence levels as a *screen*, not a statistical verdict. (The
  long-short *portfolio* uses non-overlapping rebalances; the IC series does not.)
- **AI translation can be wrong.** The LLM sometimes mis-calls an operator (wrong
  arg count, wrong column name). Static checks catch hallucinated *names*, but a
  wrong-but-plausible call only surfaces as a runtime error. In testing, a minority
  of factors failed on the first translation pass and needed a re-run or a manual fix.
  Always read the translated `compute_factor` before trusting a result.
- **Only as complete as the source file.** It scans functions that are *actually
  implemented*. A library that "has 191 alphas" but only codes 10 will scan as 10.
- **Extreme-value thresholds are heuristic** (drop forward returns > +100% or < -90%).
  Reasonable for adjusted A-share data; you may need to tune them.
- **AST classification is heuristic** and can misclassify unusual code.
- **Real-operator mode needs the project to be importable** (`--module-path`). If the
  framework has heavy import-time side effects or missing deps, this can fail.
- **Single-model dependency.** Defaults to DeepSeek; translation quality varies by
  model and by prompt. Determinism is not guaranteed across runs.
- **The GUI is less battle-tested than the CLI**, and was not tested headless during
  development. If something misbehaves in the GUI, the CLI is the reliable path.
- **Not financial advice and not production validation.** Reproduced public factors
  are frequently weak on real data; a "Weak" result is often the honest truth.

PRs that address any of these are very welcome.

---

## Roadmap / ideas

- Non-overlapping or Newey-West-adjusted IC significance
- Transaction-cost-aware long-short
- Optional industry / size neutralization (off by default, explicit when on)
- Multi-model cross-check of translations
- Better operator-signature awareness in the translation prompt

---

## Project layout

```
factorlab/
├── main.py            GUI entry
├── cli.py             single-factor CLI
├── batch_ic.py        batch IC over a whole library
├── core/              scanner, dependency, translator, static_check,
│                      executor, data_doctor, panel_utils, evaluator, report
├── llm/               client (DeepSeek/OpenAI/Anthropic) + strict prompt
├── app/gui.py         PySide6 desktop UI
└── sample/            runnable example library + operators + demo data
```

## Contributing

Issues and PRs welcome — especially around backtest rigor and translation
robustness. Please keep the "AI must not guess" principle intact: any change that
lets the model invent operators or logic defeats the purpose.

## Disclaimer

For research and educational use only. Nothing here is investment advice, and the
simplified backtest is **not** a substitute for production validation.
