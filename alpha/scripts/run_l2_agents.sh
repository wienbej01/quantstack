#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${RUN_ID:-$(date +%Y-%m-%d)_l2_impact_$(date +%H%M%S)}"

req() { [[ -f "$1" ]] || { echo "BLOCKED: missing $1" >&2; exit 2; }; }

req agents/pm.md
req agents/researcher.md
req agents/engineer.md
req agents/qa.md
req handoffs/ticket.yaml

run_codex_exec() {
  # $1 = prompt string
  codex exec --full-auto "$1"
}

echo "[1/4] PM -> handoffs/ticket.yaml"
PM_PROMPT="$(cat <<'PROMPT'
SYSTEM ROLE: PROJECT MANAGER AGENT

You are acting strictly as the Project Manager (PM).

Read and comply with the instructions in:
- agents/pm.md

Context:
- The repository already contains:
  - agents/pm.md
  - handoffs/ticket.yaml (to be overwritten)
- L2 order book data exists under: ~/quantstack/data (recursive subfolders)
- Latest L2 data is from 2026-01-22
- The system can access Polygon 1-minute OHLCV data using an API key already loaded into the shell environment from ~/.bashrc

Raw research idea:
“Analyze level-2 order book data and determine whether unusual deep liquidity has a measurable impact on price movement over a 300-second horizon.”

Your task:
- Convert the raw idea into a concrete, falsifiable, research-only ticket.

MANDATORY RULES:
- ONLY write or overwrite the file: handoffs/ticket.yaml
- DO NOT write code.
- DO NOT create or modify any other files.
- DO NOT ask questions.
- Make reasonable assumptions where information is missing and state them explicitly in the ticket.
- Scope MUST be research-only. No execution, no IBKR, no broker logic.

The ticket MUST fully specify:
- goal (one sentence, falsifiable)
- scope (research-only)
- data_inputs (explicitly referencing ~/quantstack/data and Polygon 1m OHLCV)
- definitions (conceptual placeholders only; no formulas)
- outcomes (primary = forward 300s price movement)
- acceptance_criteria (checkable pass/fail, including placebo/falsification)
- artifacts_required (exact filenames and formats)
- run_commands (concrete placeholder CLI commands)
- touched_paths_allowed (deny-by-default, restricted to research/handoffs/reports/tests)

OUTPUT FORMAT:
- Overwrite handoffs/ticket.yaml completely
- Valid YAML only
- No markdown, no commentary, no explanation

If the task cannot be completed as specified, output exactly:
BLOCKED: <short reason>

Begin now.
PROMPT
)"
run_codex_exec "$PM_PROMPT"
req handoffs/ticket.yaml

echo "[2/4] Researcher -> handoffs/experiment_spec.md"
R_PROMPT="$(cat <<'PROMPT'
SYSTEM ROLE: QUANT RESEARCHER AGENT (L2 Impact Study)

You are acting strictly as the Quant Researcher.

Read and comply with the instructions in:
- agents/researcher.md

Inputs:
- handoffs/ticket.yaml (created/updated by PM)

Your task:
- Define a falsifiable experiment for:
  “Do unusual deep L2 liquidity events predict price movement over the next 300 seconds?”
- Specify event definitions, alignment rules, estimation approach, and falsification/robustness checks.

MANDATORY RULES:
- Create or overwrite ONLY: handoffs/experiment_spec.md
- You MAY update handoffs/ticket.yaml only to refine "definitions" (do not change goal/scope/data_inputs/outcomes/artifacts/run_commands/touched_paths_allowed).
- DO NOT write code.
- DO NOT create or modify any other files.
- DO NOT ask questions. Choose sensible defaults and state assumptions.

REQUIREMENTS (must be included in experiment_spec.md):
1) At least TWO alternative event definitions for “unusual deep liquidity”
   - include depth band concept (e.g. levels 5–20) and a persistence condition
2) Time alignment rules:
   - how to map L2 timestamps (1s agg) to Polygon 1m OHLCV bars
   - how to compute forward 300s return using 1m bars (5-minute horizon)
3) Controls + normalization:
   - time-of-day bucket normalization at minimum
   - at least one additional control (e.g., trailing volatility)
4) Falsification:
   - placebo test (shuffle event times within day and time bucket)
   - lead/lag “pre-trend” check (e.g., -300s..0)
5) Estimation:
   - pooled effect + per-symbol effect
   - confidence intervals (bootstrap ok; specify seed handling)
6) Output tables expected in RESULTS.md (so engineering knows what to produce)

OUTPUT FORMAT:
- Write handoffs/experiment_spec.md as plain markdown.
- If you update ticket.yaml, it must remain valid YAML.
- No other output besides the file contents.

Begin now.
PROMPT
)"
run_codex_exec "$R_PROMPT"
req handoffs/experiment_spec.md

echo "[3/4] Engineer -> implement under research/ and write reports/${RUN_ID}/..."
E_PROMPT="$(cat <<PROMPT
SYSTEM ROLE: ENGINEER AGENT (Implement L2 Impact Experiment)

You are acting strictly as the Engineer.

Read and comply with:
- agents/engineer.md

Inputs:
- handoffs/ticket.yaml
- handoffs/experiment_spec.md

Task:
- Implement the experiment as deterministic runnable Python under research/.
- Create a CLI entrypoint matching the ticket's run_commands (update run_commands if needed, but keep intent).
- Use run id: ${RUN_ID}
- Write artifacts to: reports/${RUN_ID}/

MANDATORY RULES:
- Only modify code under: research/ (and tests/ if absolutely needed)
- Do not touch any IBKR or execution code (research-only).
- Fail loud on missing inputs or schema mismatch.
- Always write required artifacts listed in the ticket (unless blocked by missing inputs).

OUTPUT REQUIREMENTS:
- Provide a git diff
- Provide the exact command to run the experiment for this RUN_ID
- Ensure the code writes:
  - reports/${RUN_ID}/RESULTS.md
  - reports/${RUN_ID}/events.parquet
  - reports/${RUN_ID}/panel.parquet
  - reports/${RUN_ID}/metrics.csv
  - reports/${RUN_ID}/run_meta.json

Begin now.
PROMPT
)"
run_codex_exec "$E_PROMPT"

echo "[4/4] QA -> tests + gates"
Q_PROMPT="$(cat <<'PROMPT'
SYSTEM ROLE: QA AGENT (Gates + Tests)

You are acting strictly as QA.

Read and comply with:
- agents/qa.md

Inputs:
- handoffs/ticket.yaml
- research/ implementation

Task:
- Add validation gates and tests to ensure:
  - schema checks
  - timezone consistency
  - no-lookahead
  - artifact existence
  - placebo sanity
  - determinism

MANDATORY RULES:
- You may modify only: tests/ (or research/tests/) and update handoffs/ticket.yaml only by filling in test_commands if missing.
- Do not change goal/scope.
- Provide a git diff and the exact test command(s).

Begin now.
PROMPT
)"
run_codex_exec "$Q_PROMPT"

echo "DONE. Next: run the experiment using the command in handoffs/ticket.yaml (or the engineer output), with RUN_ID=${RUN_ID}"
