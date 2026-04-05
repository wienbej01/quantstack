# Alpha Homeserver Workspace

This repo branch is the homeserver development workspace for `~/quantstack/alpha`.

## Paths

- Repo: `~/trading/repos/quantstack`
- Branch: `alpha-homeserver-dev`
- Venv: `~/trading/repos/quantstack/.venv`
- Legacy L2: `~/quantstack/data/l2/l2_maximum`
- Newer L2: `~/quantstack-v2/data/l2/l2_maximum`
- SIP universes: `~/intraday_stack/data/daily_sip`
- Alpha models: `~/trading/repos/quantstack/alpha/models`
- Cached Polygon bars: `~/trading/repos/quantstack/alpha/output/polygon_ohlcv_cache`

## Current bar-source behavior

`alpha/scripts/run_hypothesis_test.py` now tries the configured `bar_source` first and
automatically falls back to the alternate source.

For the current 2026 alpha/L2 windows:

- `gold` data is incomplete from the configured `~/gcs-mount/gold/stocks` path
- cached Polygon bars are present under `alpha/output/polygon_ohlcv_cache`

That means the safest default for homeserver development is:

```bash
python alpha/scripts/run_hypothesis_test.py --hypothesis ml --start 2026-03-09 --end 2026-03-20 --bar-source polygon
```

If you forget `--bar-source polygon`, the script will still fall back to Polygon when
Gold is unavailable.

## Bootstrap

Run this after pulling updates or if the workspace looks stale:

```bash
cd ~/trading/repos/quantstack
alpha/scripts/bootstrap_homeserver_alpha.sh
```

That script:

- updates the repo to `alpha-homeserver-dev`
- ensures the venv exists
- installs Python dependencies
- verifies L2, SIP, model, and Polygon cache paths
- runs a non-destructive alpha CLI smoke test

## Development flow

```bash
cd ~/trading/repos/quantstack
source .venv/bin/activate
git status
```

Make code changes on `alpha-homeserver-dev`, commit normally, and push that branch.

Do not use git for:

- `alpha/output/`
- `alpha/reports/`
- L2 datasets
- model `.pkl` artifacts
- cached bars

Those are runtime assets, not source.
