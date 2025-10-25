#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REQ_TRADE_COLS = {
    "entry_ts",
    "exit_ts",
    "symbol",
    "side",
    "qty",
    "entry_px",
    "exit_px",
    "pnl",
}
REQ_METRIC_KEYS = [
    "trades",
    "avg_R",
    "ES_95",
    "pvalue_u",
    "sharpe_CI_low",
    "sharpe_CI_high",
    "capacity_break_even_bps",
]


def check_trades(run_dir: Path):
    fp = next(run_dir.rglob("trades.parquet"), None)
    if not fp:
        raise FileNotFoundError(f"No trades.parquet in {run_dir}")
    df = pd.read_parquet(fp)
    if not df.empty:
        missing = REQ_TRADE_COLS - set(df.columns)
        if missing:
            raise AssertionError(f"trades missing columns: {missing}")
        if df["pnl"].isna().any():
            raise AssertionError("NaNs detected in pnl")
    return str(fp)


def check_metrics(run_dir: Path):
    fp = next(run_dir.rglob("metrics.json"), None)
    if not fp:
        raise FileNotFoundError(f"No metrics.json in {run_dir}")
    m = json.loads(Path(fp).read_text())
    for k in REQ_METRIC_KEYS:
        if k not in m:
            raise AssertionError(f"metrics missing key: {k}")
    return str(fp)


def main():
    ap = argparse.ArgumentParser(
        description="Validate artifacts emitted by experiments harness"
    )
    ap.add_argument("--runs-root", default="runs", help="Root where run_* folders live")
    args = ap.parse_args()

    runs_root = Path(args.runs_root)
    if not runs_root.exists():
        print(f"[error] runs root not found: {runs_root}", file=sys.stderr)
        sys.exit(2)

    run_dirs = sorted([p for p in runs_root.glob("*") if p.is_dir()])
    if not run_dirs:
        print("[error] no runs found", file=sys.stderr)
        sys.exit(2)

    ok = True
    for rd in run_dirs:
        try:
            t = check_trades(rd)
            m = check_metrics(rd)
            print(f"[ok] {rd.name}: trades={t} metrics={m}")
        except Exception as e:
            ok = False
            print(f"[fail] {rd.name}: {e}", file=sys.stderr)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
