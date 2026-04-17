# Alpha ML Paper Trading System - 2026-04-06

## Scope

Implemented a homeserver alpha ML paper/shadow trading service using the repaired
action-ranker baseline:

- artifact: `alpha/models/action_ranker_xgb_2026-03-19.pkl`
- policy: ungated, `daily_top_k=4`, `max_longs_per_day=2`, `min_score=0.5`
- bar source: Polygon cache/API path
- SIP source: `/home/jacobw/intraday_stack/data/daily_sip`
- L2 source: existing alpha `L2Loader` multi-root union

This is paper/shadow only. It writes trade intents and status files. It does not
import or call any order manager or IBKR execution adapter.

## Reused Mechanisms

- Reuses the alpha budget backtest scorer for action-ranker feature generation
  and top-K selection.
- Reuses the same daily SIP ticker source as l2-scalping.
- Mirrors the l2-scalping SIP filter behavior:
  - skip known ARCA symbols
  - default unknown equities to NYSE-eligible
  - cap default symbols at `3` to match the L2 subscription constraint pattern
- Reuses homeserver user-systemd timer pattern:
  - service starts after market open
  - stop timer runs after market close
  - launcher fails closed if SIP is missing

## Files Added

- `alpha/src/paper_trading/action_ranker_paper.py`
- `alpha/src/paper_trading/__init__.py`
- `alpha/scripts/run_alpha_ml_paper_trading.py`
- `alpha/scripts/start_alpha_ml_paper_trading.sh`
- `alpha/scripts/install_alpha_paper_systemd.sh`
- `systemd/alpha-ml-paper-trading.service`
- `systemd/alpha-ml-paper-trading.timer`
- `systemd/alpha-ml-paper-trading-stop.service`
- `systemd/alpha-ml-paper-trading-stop.timer`
- `alpha/tests/test_alpha_paper_trading.py`

## Runtime Outputs

Production service outputs are written under:

- `alpha/output/paper_trading/action_ranker/date=YYYY-MM-DD/status.json`
- `alpha/output/paper_trading/action_ranker/date=YYYY-MM-DD/latest_signals.json`
- `alpha/output/paper_trading/action_ranker/date=YYYY-MM-DD/paper_signals.jsonl`
- `alpha/output/paper_trading/action_ranker/date=YYYY-MM-DD/ranked_actions.csv`
- `alpha/output/paper_trading/action_ranker/date=YYYY-MM-DD/selected_actions.csv`

## Systemd Integration

Installed into user-systemd:

- `alpha-ml-paper-trading.timer`
- `alpha-ml-paper-trading.service`
- `alpha-ml-paper-trading-stop.timer`
- `alpha-ml-paper-trading-stop.service`

Timer schedule:

- start: `Mon-Fri 09:31:00 America/New_York`
- stop: `Mon-Fri 16:05:00 America/New_York`

Install command used:

```bash
bash alpha/scripts/install_alpha_paper_systemd.sh
```

Verification:

```bash
systemd-analyze --user verify \
  systemd/alpha-ml-paper-trading.service \
  systemd/alpha-ml-paper-trading.timer \
  systemd/alpha-ml-paper-trading-stop.service \
  systemd/alpha-ml-paper-trading-stop.timer
```

Result: passed.

Timer status after install:

- `alpha-ml-paper-trading.timer`: active/waiting
- `alpha-ml-paper-trading-stop.timer`: active/waiting

## Smoke Test

Production-default one-shot smoke:

```bash
timeout 180 .venv/bin/python alpha/scripts/run_alpha_ml_paper_trading.py \
  --date 2026-02-18 \
  --cutoff-et 15:59:00 \
  --allow-outside-hours \
  --output-dir alpha/output/paper_trading/smoke_action_ranker_default
```

Result:

- status: `ok`
- SIP symbols: `21`
- selected SIP/L2-scalping symbols: `F`, `NVDA`, `KHC`
- loaded bars/L2 for `F` and `NVDA`
- skipped `KHC` because cached Polygon bars were unavailable for that historical date
- ranked actions: `158`
- selected paper intents: `4`
- new paper signals appended: `4`

Smoke output:

- `alpha/output/paper_trading/smoke_action_ranker_default/date=2026-02-18/status.json`
- `alpha/output/paper_trading/smoke_action_ranker_default/date=2026-02-18/latest_signals.json`
- `alpha/output/paper_trading/smoke_action_ranker_default/date=2026-02-18/paper_signals.jsonl`
- `alpha/output/paper_trading/smoke_action_ranker_default/date=2026-02-18/ranked_actions.csv`
- `alpha/output/paper_trading/smoke_action_ranker_default/date=2026-02-18/selected_actions.csv`

Broader smoke with `--max-symbols 10` also passed:

- ranked actions: `286`
- selected paper intents: `4`

## Test Verification

```bash
timeout 180 .venv/bin/python -m pytest \
  alpha/tests/test_alpha_paper_trading.py \
  alpha/tests/test_ml_dataset.py \
  alpha/tests/test_action_ranker.py \
  alpha/tests/test_data_loaders.py -q
```

Result: `47 passed, 5 skipped`.

Additional checks:

- `bash -n alpha/scripts/start_alpha_ml_paper_trading.sh`: passed
- `bash -n alpha/scripts/install_alpha_paper_systemd.sh`: passed
- `timeout 180 .venv/bin/python -m py_compile ...`: passed
- `git diff --check`: passed

## Current Operational Blocker

At verification time, the ET date was `2026-04-06`, and the official SIP file was
missing:

```text
/home/jacobw/intraday_stack/data/daily_sip/date=2026-04-06/sip_universe.json
```

The installed service will therefore fail closed at startup until the daily SIP
generator writes the current-date file.

## Operational Notes

- This service is suitable for supervised paper/shadow validation only.
- It should not be treated as live-capital ready.
- The service intentionally uses the repaired production baseline instead of any
  rejected `2026-04-06` retraining variant.
- The default l2-scalping-style cap can underuse the model when one of the first
  three SIP tickers has missing bars. Increase `ALPHA_PAPER_MAX_SYMBOLS` only if
  the L2/market-data subscription budget supports it.

