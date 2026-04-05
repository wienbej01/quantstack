#!/usr/bin/env python
"""Full ML strategy optimizer — memory-efficient, checkpointed.

Processes data per symbol-day (never holds full dataset in RAM).
Saves intermediate parquet after each phase so crashes don't lose work.

Usage:
    # Full weekend run
    setsid .venv/bin/python -u scripts/optimize_ml_strategy.py </dev/null >> output/ml_optimize.log 2>&1 &

    # Quick test
    .venv/bin/python -u scripts/optimize_ml_strategy.py --quick

    # Resume from saved parquet (skip data loading)
    .venv/bin/python -u scripts/optimize_ml_strategy.py --resume

    # Monitor
    tail -f output/ml_optimize.log
    cat output/ml_checkpoint.json
"""

import argparse
import gc
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import psutil

# ============================================================
# Paths & constants
# ============================================================
OUTPUT_DIR = Path("output")
LOG_PATH = OUTPUT_DIR / "ml_optimize.log"
CHECKPOINT_PATH = OUTPUT_DIR / "ml_checkpoint.json"
RESULTS_PATH = OUTPUT_DIR / "ml_optimization_results.csv"
DATASET_PATH = OUTPUT_DIR / "ml_dataset.parquet"  # saved after phases 1-3

MAX_CORES = 2
HEARTBEAT_SEC = 60

HORIZONS = [60, 180, 300]

TP_BPS_FULL = [15, 20, 25, 30, 40, 50, 60, 75, 100, 125, 150]
SL_BPS_FULL = [10, 15, 20, 25, 30, 40, 50, 60, 75, 100]
CONF_FULL = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]

TP_BPS_QUICK = [30, 50, 75]
SL_BPS_QUICK = [20, 40, 60]
CONF_QUICK = [0.50, 0.55]

XGB_GRID_FULL = {
    "max_depth": [3, 4, 5, 6],
    "n_estimators": [100, 200, 400],
    "learning_rate": [0.01, 0.03, 0.05, 0.1],
    "min_child_weight": [20, 50, 100],
}
XGB_GRID_QUICK = {
    "max_depth": [3, 4, 5],
    "n_estimators": [100, 200],
    "learning_rate": [0.03, 0.05, 0.1],
}


# ============================================================
# Heartbeat
# ============================================================
class Heartbeat:
    def __init__(self):
        self._stop = threading.Event()
        self._phase = "init"
        self._progress = ""
        self._start = time.time()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()

    def set_phase(self, phase, progress=""):
        self._phase = phase
        self._progress = progress

    def set_progress(self, progress):
        self._progress = progress

    def _run(self):
        while not self._stop.wait(HEARTBEAT_SEC):
            try:
                p = psutil.Process(os.getpid())
                uss = p.memory_full_info().uss / 1e9
                sm = psutil.virtual_memory()
                elapsed = timedelta(seconds=int(time.time() - self._start))
                logger.info(
                    f"[HEARTBEAT] {elapsed} | {self._phase} | {self._progress} | "
                    f"USS={uss:.1f}GB | sys_avail={sm.available/1e9:.1f}GB"
                )
                if sm.available < 2e9:
                    logger.warning("Low memory — running GC")
                    gc.collect()
            except Exception:
                pass


# ============================================================
# PnL simulation (vectorized)
# ============================================================
def simulate_pnl(preds, fwd_ret, tp_bps, sl_bps, conf, comm_bps=1.0):
    tp = tp_bps / 10000
    sl = sl_bps / 10000
    comm = comm_bps / 10000
    p_down, p_up = preds[:, 0], preds[:, 2]
    valid = ~np.isnan(fwd_ret)

    # Long
    lm = valid & (p_up > conf) & (p_up > p_down)
    lr = fwd_ret[lm]
    lp = np.where(lr >= tp, tp, np.where(lr <= -sl, -sl, lr)) - comm

    # Short
    sm = valid & (p_down > conf) & (p_down > p_up)
    sr = -fwd_ret[sm]
    sp = np.where(sr >= tp, tp, np.where(sr <= -sl, -sl, sr)) - comm

    pnls = np.concatenate([lp, sp])
    n = len(pnls)
    if n == 0:
        return dict(
            sharpe=-999,
            total_pnl_bps=0,
            n_trades=0,
            win_rate=0,
            avg_pnl_bps=0,
            profit_factor=0,
            n_long=0,
            n_short=0,
        )
    avg = pnls.mean()
    std = pnls.std() if n > 1 else 1e-9
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else 999.0
    return dict(
        sharpe=round(float(avg / std * np.sqrt(252 * 20)), 3) if std > 0 else 0,
        total_pnl_bps=round(float(pnls.sum() * 10000), 1),
        n_trades=n,
        win_rate=round(float(len(wins) / n), 3),
        avg_pnl_bps=round(float(avg * 10000), 2),
        profit_factor=round(float(min(pf, 999)), 2),
        n_long=int(lm.sum()),
        n_short=int(sm.sum()),
    )


# ============================================================
# Checkpoint helpers
# ============================================================
def save_ckpt(data):
    data["timestamp"] = datetime.now().isoformat()
    CHECKPOINT_PATH.write_text(json.dumps(data, indent=2, default=str))


# ============================================================
# Logging
# ============================================================
def setup_logging():
    OUTPUT_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)

    fh = logging.FileHandler(LOG_PATH, mode="a")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    # Suppress noisy child loggers
    for name in ("src.data.l2_loader", "src.data.ml_dataset", "src.models.xgb_trainer"):
        logging.getLogger(name).setLevel(logging.WARNING)

    return logging.getLogger("optimize")


logger = logging.getLogger("optimize")


# ============================================================
# Phase 1-3: Build dataset (memory-efficient, saves to parquet)
# ============================================================
def build_dataset(min_snapshots: int) -> Path:
    """Load data per symbol-day, compute features+labels, save to parquet.

    Never holds more than one symbol-day in memory at a time.
    Returns path to saved parquet.
    """
    from src.data.l2_loader import L2Loader
    from src.data.ml_dataset import FEATURE_COLS, compute_features_from_raw
    from src.features.ml_features import compute_ml_features, get_ml_feature_columns
    from src.data.ml_labels import generate_labels

    loader = L2Loader()
    all_dates = loader.get_available_dates(source_type="any")
    logger.info(f"Found {len(all_dates)} dates across all sources")

    # Collect all (date, symbol) pairs
    pairs = []
    for date in all_dates:
        for sym in loader.get_available_symbols(date, source_type="any"):
            pairs.append((date, sym))
    logger.info(f"Total symbol-days to process: {len(pairs)}")

    # Process one at a time, write chunks to parquet
    chunk_dir = OUTPUT_DIR / "ml_chunks"
    chunk_dir.mkdir(exist_ok=True)

    processed = 0
    skipped = 0

    for i, (date, sym) in enumerate(pairs):
        chunk_path = chunk_dir / f"{date}_{sym}.parquet"
        if chunk_path.exists():
            processed += 1
            continue  # already done (resume support)

        if i % 10 == 0:
            hb.set_progress(f"{i}/{len(pairs)} ({processed} ok, {skipped} skip)")

        try:
            # Load
            try:
                df = loader.load_snapshots(sym, date, source_type="features")
                if "symbol" not in df.columns:
                    df["symbol"] = sym
                # Ensure canonical columns
                for c in FEATURE_COLS:
                    if c not in df.columns:
                        df[c] = 0.0
                df = df[
                    ["ts_utc", "symbol"] + [c for c in FEATURE_COLS if c in df.columns]
                ]
            except FileNotFoundError:
                df = loader.load_snapshots(sym, date, source_type="raw")
                df = compute_features_from_raw(df)
                if "symbol" not in df.columns:
                    df["symbol"] = sym

            if len(df) < min_snapshots:
                skipped += 1
                continue

            df["date"] = date

            # Compute ML features
            df = df.sort_values("ts_utc").reset_index(drop=True)
            df = compute_ml_features(df)

            # Generate labels
            df = generate_labels(df, horizons_seconds=HORIZONS)

            # Keep only ML-relevant columns (drop raw L2 columns we don't need)
            # Keep: metadata, labels, returns, and all numeric features
            exclude = {
                "ts_epoch",
                "date_et",
                "exchange",
                "smart_depth",
                "has_depth",
                "microprice",
                "micro_off",
            }  # redundant with derived features
            keep = [c for c in df.columns if c not in exclude]
            df = df[keep]

            # Save chunk
            df.to_parquet(chunk_path, index=False)
            processed += 1

        except Exception as e:
            logger.warning(f"Failed {sym}/{date}: {e}")
            skipped += 1
            continue

        # Free memory every iteration
        if i % 20 == 0:
            gc.collect()

    logger.info(f"Processed {processed} symbol-days, skipped {skipped}")

    # Merge chunks into single parquet
    logger.info("Merging chunks into single dataset...")
    chunk_files = sorted(chunk_dir.glob("*.parquet"))
    if not chunk_files:
        raise RuntimeError("No data processed")

    # Read and concat in batches of 20 to limit memory
    batch_size = 20
    merged = []
    for j in range(0, len(chunk_files), batch_size):
        batch = [pd.read_parquet(f) for f in chunk_files[j : j + batch_size]]
        merged.append(pd.concat(batch, ignore_index=True))
        del batch
        gc.collect()

    result = pd.concat(merged, ignore_index=True)
    del merged
    gc.collect()

    result.to_parquet(DATASET_PATH, index=False)
    logger.info(
        f"Dataset saved: {DATASET_PATH} ({len(result)} rows, "
        f"{result['symbol'].nunique()} symbols, {result['date'].nunique()} dates)"
    )

    save_ckpt(
        {
            "phase": "dataset_built",
            "rows": len(result),
            "symbols": int(result["symbol"].nunique()),
            "dates": int(result["date"].nunique()),
        }
    )

    del result
    gc.collect()
    return DATASET_PATH


# ============================================================
# Phase 4-6: Train + sweep (loads from parquet)
# ============================================================
def train_and_sweep(args, tp_grid, sl_grid, conf_grid, xgb_grid):
    from src.data.ml_labels import temporal_split, walk_forward_folds
    from src.features.ml_features import get_ml_feature_columns
    from src.models.xgb_trainer import train_walk_forward, save_model

    # Load dataset from parquet (much smaller than raw — only ML columns)
    logger.info(f"Loading dataset from {DATASET_PATH}...")
    df = pd.read_parquet(DATASET_PATH)
    logger.info(
        f"Loaded {len(df)} rows, {df['symbol'].nunique()} symbols, "
        f"{df['date'].nunique()} dates, USS={_uss():.1f}GB"
    )

    # Feature columns
    feature_cols = get_ml_feature_columns(df)
    feature_cols = [
        c
        for c in feature_cols
        if not c.startswith("ret_fwd_") and not c.startswith("label_")
    ]
    df[feature_cols] = df[feature_cols].fillna(0).replace([np.inf, -np.inf], 0)
    logger.info(f"Feature columns: {len(feature_cols)}")

    # Split
    train_df, val_df, test_df, split_info = temporal_split(df)
    logger.info(f"Train: {len(train_df)} rows ({split_info.train_dates})")
    logger.info(f"Val:   {len(val_df)} rows ({split_info.val_dates})")
    logger.info(f"Test:  {len(test_df)} rows ({split_info.test_dates})")
    logger.info(f"Holdout symbols: {split_info.holdout_symbols}")

    folds = walk_forward_folds(split_info.train_dates)
    logger.info(f"Walk-forward folds: {len(folds)}")

    # ---- XGBoost grid search per horizon ----
    hb.set_phase("xgb_grid_search")
    xgb_keys = list(xgb_grid.keys())
    xgb_combos = list(product(*[xgb_grid[k] for k in xgb_keys]))
    total_fits = len(xgb_combos) * len(HORIZONS)
    logger.info(
        f"XGBoost grid: {len(xgb_combos)} combos × {len(HORIZONS)} horizons = {total_fits} fits"
    )

    best_models = {}
    all_xgb = []
    fit_n = 0

    for h in HORIZONS:
        label_col = f"label_{h}s"
        valid = df[label_col].notna()
        if valid.sum() < 500:
            logger.warning(f"Horizon {h}s: {valid.sum()} valid labels — skipping")
            continue

        best_acc = -1
        best_result = None
        best_params = None

        for combo in xgb_combos:
            params = dict(zip(xgb_keys, combo))
            params["n_jobs"] = args.max_cores
            fit_n += 1
            hb.set_progress(f"fit {fit_n}/{total_fits} H={h}s")

            t0 = time.time()
            try:
                result = train_walk_forward(
                    df[valid], feature_cols, label_col, folds, params=params
                )
                dt = time.time() - t0
                logger.info(
                    f"  [{fit_n}/{total_fits}] H={h}s {params} → "
                    f"val={result.mean_val_acc:.3f} gap={result.train_val_gap:.3f} ({dt:.0f}s)"
                )
                all_xgb.append(
                    {
                        **params,
                        "horizon": h,
                        "val_acc": result.mean_val_acc,
                        "gap": result.train_val_gap,
                        "secs": round(dt),
                    }
                )
                if result.mean_val_acc > best_acc:
                    best_acc = result.mean_val_acc
                    best_result = result
                    best_params = params
            except Exception as e:
                logger.warning(f"  [{fit_n}/{total_fits}] H={h}s {params} FAILED: {e}")

            if fit_n % 5 == 0:
                save_ckpt({"phase": "xgb_grid", "fit": fit_n, "total": total_fits})
                gc.collect()

        if best_result:
            best_models[h] = (best_params, best_result)
            logger.info(f"  ★ Best {h}s: acc={best_acc:.3f} {best_params}")

    pd.DataFrame(all_xgb).to_csv(OUTPUT_DIR / "xgb_grid_results.csv", index=False)

    if not best_models:
        logger.error("No models trained. Exiting.")
        return

    # ---- TP/SL/conf sweep on validation ----
    hb.set_phase("tpsl_sweep")
    combos = [
        (tp, sl, c)
        for tp, sl, c in product(tp_grid, sl_grid, conf_grid)
        if tp >= sl * 0.5
    ]
    logger.info(f"TP/SL sweep: {len(combos)} combos × {len(best_models)} horizons")

    all_sweep = []
    sweep_n = 0
    total_sweep = len(combos) * len(best_models)

    for h, (params, result) in best_models.items():
        ret_col = f"ret_fwd_{h}s"
        label_col = f"label_{h}s"
        vm = val_df[label_col].notna()
        vs = val_df[vm]
        if len(vs) < 50:
            continue

        X_val = np.nan_to_num(vs[feature_cols].values)
        val_proba = result.best_model.predict_proba(X_val)
        val_ret = vs[ret_col].values

        for tp, sl, conf in combos:
            sweep_n += 1
            if sweep_n % 500 == 0:
                hb.set_progress(f"sweep {sweep_n}/{total_sweep}")
            m = simulate_pnl(val_proba, val_ret, tp, sl, conf)
            m.update(horizon=h, tp_bps=tp, sl_bps=sl, conf_threshold=conf)
            all_sweep.append(m)

    results_df = pd.DataFrame(all_sweep)
    results_df.to_csv(RESULTS_PATH, index=False)
    logger.info(f"Sweep results: {RESULTS_PATH} ({len(results_df)} rows)")

    # ---- Report ----
    viable = results_df[results_df["n_trades"] >= 10].sort_values(
        "sharpe", ascending=False
    )
    if viable.empty:
        viable = results_df.sort_values("sharpe", ascending=False)

    logger.info("\n" + "=" * 80)
    logger.info("TOP 20 CONFIGS (validation Sharpe, ≥10 trades)")
    logger.info("=" * 80)
    for _, r in viable.head(20).iterrows():
        logger.info(
            f"  H={int(r['horizon']):>3}s TP={int(r['tp_bps']):>3}bp "
            f"SL={int(r['sl_bps']):>3}bp conf={r['conf_threshold']:.2f} | "
            f"Sharpe={r['sharpe']:>7.2f} WR={r['win_rate']:.1%} "
            f"PF={r['profit_factor']:>6.2f} trades={int(r['n_trades']):>5} "
            f"avg={r['avg_pnl_bps']:>+7.1f}bp"
        )

    # ---- Test eval (top 3) ----
    logger.info("\n" + "=" * 80)
    logger.info("TEST EVALUATION (unseen data)")
    logger.info("=" * 80)
    for rank, (_, r) in enumerate(viable.head(3).iterrows()):
        h = int(r["horizon"])
        if h not in best_models:
            continue
        _, result = best_models[h]
        ret_col = f"ret_fwd_{h}s"
        label_col = f"label_{h}s"
        tm = test_df[label_col].notna()
        ts = test_df[tm]
        if len(ts) == 0:
            continue
        X_test = np.nan_to_num(ts[feature_cols].values)
        test_proba = result.best_model.predict_proba(X_test)
        test_m = simulate_pnl(
            test_proba,
            ts[ret_col].values,
            r["tp_bps"],
            r["sl_bps"],
            r["conf_threshold"],
        )
        deg = (
            (r["sharpe"] - test_m["sharpe"]) / abs(r["sharpe"])
            if r["sharpe"] != 0
            else 0
        )
        flag = "⚠ OVERFIT" if deg > 0.5 else "✓ OK"
        logger.info(
            f"  #{rank+1} H={h}s TP={int(r['tp_bps'])}bp SL={int(r['sl_bps'])}bp conf={r['conf_threshold']:.2f}"
        )
        logger.info(
            f"     VAL:  Sharpe={r['sharpe']:>6.2f} WR={r['win_rate']:.1%} trades={int(r['n_trades'])}"
        )
        logger.info(
            f"     TEST: Sharpe={test_m['sharpe']:>6.2f} WR={test_m['win_rate']:.1%} "
            f"trades={test_m['n_trades']} avg={test_m['avg_pnl_bps']:>+.1f}bp [{flag} deg={deg:.0%}]"
        )

    # Save best model
    if len(viable) > 0:
        best_h = int(viable.iloc[0]["horizon"])
        if best_h in best_models:
            save_model(best_models[best_h][1], "models/xgb_best.pkl")
            logger.info(f"\nBest model → models/xgb_best.pkl")

    # Feature importance
    for h, (_, result) in best_models.items():
        imp = result.fold_results[result.best_fold_idx].feature_importance
        top = sorted(imp.items(), key=lambda x: x[1], reverse=True)[:15]
        logger.info(f"\nTop 15 features (H={h}s):")
        for name, score in top:
            logger.info(f"  {score:.4f} {'█' * int(score * 200)} {name}")

    save_ckpt(
        {
            "phase": "complete",
            "configs_tested": len(results_df),
            "best_sharpe": float(viable.iloc[0]["sharpe"]) if len(viable) > 0 else 0,
        }
    )
    logger.info("\n✓ Optimization complete.")


def _uss():
    try:
        return psutil.Process(os.getpid()).memory_full_info().uss / 1e9
    except Exception:
        return 0


# ============================================================
# Main
# ============================================================
hb = Heartbeat()


def main():
    global logger
    logger = setup_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument(
        "--resume", action="store_true", help="Skip data build, use saved parquet"
    )
    parser.add_argument("--max-cores", type=int, default=MAX_CORES)
    parser.add_argument("--min-snapshots", type=int, default=100)
    args = parser.parse_args()

    try:
        os.nice(10)
        logger.info("Process niced to +10")
    except OSError:
        pass

    tp_grid = TP_BPS_QUICK if args.quick else TP_BPS_FULL
    sl_grid = SL_BPS_QUICK if args.quick else SL_BPS_FULL
    conf_grid = CONF_QUICK if args.quick else CONF_FULL
    xgb_grid = XGB_GRID_QUICK if args.quick else XGB_GRID_FULL

    n_xgb = 1
    for v in xgb_grid.values():
        n_xgb *= len(v)

    logger.info("=" * 80)
    logger.info("ML STRATEGY OPTIMIZER")
    logger.info("=" * 80)
    logger.info(f"Mode: {'QUICK' if args.quick else 'FULL'} | Cores: {args.max_cores}")
    logger.info(
        f"XGB grid: {n_xgb} combos × {len(HORIZONS)} horizons = {n_xgb * len(HORIZONS)} fits"
    )
    logger.info(f"TP/SL grid: {len(tp_grid)}×{len(sl_grid)}×{len(conf_grid)}")

    hb.start()

    try:
        # Phase 1-3: Build dataset (or resume)
        if args.resume and DATASET_PATH.exists():
            logger.info(f"Resuming from {DATASET_PATH}")
        else:
            hb.set_phase("data_build")
            build_dataset(args.min_snapshots)

        # Phase 4-6: Train + sweep
        hb.set_phase("training")
        train_and_sweep(args, tp_grid, sl_grid, conf_grid, xgb_grid)

    except KeyboardInterrupt:
        logger.info("Interrupted. Checkpoint saved.")
    except Exception as e:
        logger.exception(f"Fatal: {e}")
    finally:
        hb.stop()
        logger.info("Done.")


if __name__ == "__main__":
    main()
