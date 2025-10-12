# Pilot Test Playbook — VWAP Mean‑Reversion (v2.1)

You say all sprints 1.9–1.17 are done. Great. Now we try to break it politely.

## 1) Pre‑flight (read‑only, zero drama)
```bash
cd ~/quantstack
source .venv/bin/activate
python -m qx_cli exp --help
```
You should see the exp subcommands. If not, your install is borked.

## 2) Data sanity (Gold only; no lake writes)
Inspect a tiny Gold slice (AAPL Jan‑2024) and optionally create a tiny sample under /tmp:
```bash
python ~/quantstack/tools/check_gold_and_make_smoke_sample.py   --gold-root /home/jacobw/gcs-mount/gold   --family bars_1m   --symbol AAPL --year 2024 --month 01 --n-files 2   --write-sample --out-dir /tmp/e2e_smoke_from_gold
```
Point your configs either to real Gold or to `/tmp/e2e_smoke_from_gold`.

## 3) Run the pilot A/B (SIP on vs off, or thresholds)
```bash
python -m qx_cli exp entry-ab   --cfg experiments/vwap_revert/strategy.yaml   --variants experiments/vwap_revert/overlays/policy_*.yaml   --name vwap_revert_pilot
```
Artifacts expected:
- `experiments/vwap_revert_pilot/{manifest.json, inputs_checksum.json, compare.{json,md}}`
- `runs/<run_id>/{signals,orders,fills,positions,equity}.parquet`
- `runs/<run_id>/{trades,risk_rejects,allocation_log}.parquet`
- `runs/<run_id>/metrics.json`

## 4) Validate artifacts (hard fail on schema issues)
```bash
python ~/quantstack/tools/test_exp_artifacts.py --runs-root runs
```
This checks required trade columns and extended metric keys.

## 5) Fairness & reproducibility
Re‑run with the same seed and confirm identical checksums:
```bash
python -m qx_cli exp entry-ab   --cfg experiments/vwap_revert/strategy.yaml   --variants experiments/vwap_revert/overlays/policy_*.yaml   --name vwap_revert_pilot_repeat
```
Compare `experiments/*/inputs_checksum.json` across runs. They should match bit‑for‑bit unless you changed configs or data.

Force a mismatch (change `seed` or features) and confirm the compare refuses to run unless `--force` is passed.

## 6) Extended probes (quick pain, big signal)
- **Cost sweep** (sensitivity to bps and skid):
```bash
python -m qx_cli exp cost-sweep   --cfg experiments/vwap_revert/strategy.yaml   --grid "bps=0.5,1,2 slippage_ticks=0,1,2"   --name vwap_revert_costs
```
- **Risk grid** (position sizing stress):
```bash
python -m qx_cli exp risk-grid   --cfg experiments/vwap_revert/strategy.yaml   --grid "max_risk_frac=0.005,0.01,0.02"   --name vwap_revert_risk
```
- **Regime slice** (stability checks):
```bash
python -m qx_cli exp regime-slice   --cfg experiments/vwap_revert/strategy.yaml   --regimes vol_tercile,session,dow   --name vwap_revert_regimes
```

## 7) Smoke gates (fail fast rules)
- ≥ 10 trades per variant.
- No NaN in `pnl` or prices.
- Equity equals cumulative PnL (plus initial).
- Warmup respected (no trades before feature windows ready).
- `compare.md` renders and includes U‑test p‑value and bootstrap CIs.

## 8) Triage guide (when things go sideways)
- **No trades** → warmup window too long, SIP filter empty, or policy thresholds too strict.
- **Checksum mismatch** → hidden nondeterminism; check seeds, sort orders, row ordering, dtype coercions.
- **Equity drift vs PnL** → fees/slippage double‑counted or positions not flat at end.
- **High<Low violations** → upstream data issue; exclude affected bars in‑memory only.

## 9) CI hook (optional, but you’ll thank me)
Run a tiny E2E on push:
```bash
pytest -q
python ~/quantstack/tools/test_exp_artifacts.py --runs-root runs
```
Wire it in whichever CI you use. Keep it short to avoid rage.

## 10) What “good enough” looks like for the pilot
- Both variants produce trades and plausible metrics.
- Fairness checksums match on re‑run.
- Cost and risk sweeps don’t implode metrics.
- `compare.md` highlights meaningful differences (even if they’re “both bad” — clarity beats hopium).
