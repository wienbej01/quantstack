"""Parallel policy sweep with trade-level analysis."""
import argparse
import json
import logging
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any
import pandas as pd
import yaml

from extensions.intraday_ml.experiments.policy_sweep import (
    load_frame,
    expand_parameter_grid,
    apply_overrides,
    _prepare_signals_for_policy_mode,
    _ensure_required_columns,
    _count_trading_days,
)
from extensions.intraday_ml.backtest import intraday_ml_run_backtest
from extensions.intraday_ml.policy.rejection_reasons import REJECTION_REASON_TO_COLUMN
from extensions.intraday_ml_policies.intraday_ml_decision_policy import IntradayMLDecisionPolicy
from extensions.intraday_ml.diagnostics.trade_analyzer import TradeAnalyzer

LOGGER = logging.getLogger(__name__)


def run_single_config(
    sweep_id: int,
    overrides: dict[str, Any],
    signals: pd.DataFrame,
    bars: pd.DataFrame,
    base_policy_config: dict[str, Any],
    backtest_config: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Run a single configuration and save trades."""
    try:
        # Apply overrides
        policy_cfg = base_policy_config.copy()
        apply_overrides(policy_cfg, overrides)
        
        # Create policy
        policy = IntradayMLDecisionPolicy(policy_cfg)
        
        # Prepare signals
        sweep_signals = _prepare_signals_for_policy_mode(signals, policy_cfg.get("policy_mode"))
        sweep_signals = sweep_signals.copy()
        
        required_columns = (
            policy.get_required_feature_columns()
            if hasattr(policy, "get_required_feature_columns")
            else set()
        )
        sweep_signals = _ensure_required_columns(sweep_signals, bars, required_columns=required_columns)
        
        # Process signals
        orders, rejections = policy.process_signals(sweep_signals)
        rejection_counts = policy.get_rejection_reason_counts()
        
        # Run backtest
        artifacts = intraday_ml_run_backtest(bars, orders, cfg=backtest_config)
        
        # Extract metrics
        entry_orders = orders[orders["reason"] == "trade"] if not orders.empty else orders
        trade_count = len(entry_orders)
        trading_days = max(1, _count_trading_days(bars))
        trades_per_day = trade_count / trading_days
        
        trades_df = artifacts.get("trades")
        hit_rate = float("nan")
        avg_r = float("nan")
        if isinstance(trades_df, pd.DataFrame) and not trades_df.empty:
            r_values = trades_df["r_multiple"]
            avg_r = float(r_values.mean())
            hit_rate = float((r_values > 0).mean())
            
            # Save trades for this config
            trades_path = output_dir / f"trades_config_{sweep_id:04d}.parquet"
            trades_df.to_parquet(trades_path, index=False)
            
            # Analyze trades
            analyzer = TradeAnalyzer(trades_df, sweep_id, overrides)
            analysis = analyzer.analyze()
            
            # Save analysis
            analysis_path = output_dir / f"analysis_config_{sweep_id:04d}.json"
            with open(analysis_path, 'w') as f:
                json.dump(analysis, f, indent=2, default=str)
        
        metrics = artifacts.get("metrics", {})
        metrics_prefixed = {f"metric_{key}": value for key, value in metrics.items()}
        
        row = {
            "sweep_id": sweep_id,
            "entries": trade_count,
            "rejections": len(rejections),
            "trades_per_day": trades_per_day,
            "avg_r_multiple": avg_r,
            "hit_rate": hit_rate,
            "rejection_counts": dict(rejection_counts),
        }
        
        for reason_key, column_name in REJECTION_REASON_TO_COLUMN.items():
            row[column_name] = int(rejection_counts.get(reason_key, 0))
        
        row.update(metrics_prefixed)
        
        for key, value in overrides.items():
            row[f"param_{key}"] = value
        
        return row
        
    except Exception as e:
        LOGGER.error(f"Config {sweep_id} failed: {e}")
        return {
            "sweep_id": sweep_id,
            "error": str(e),
            "entries": 0,
            "rejections": 0,
        }


def parallel_sweep(
    signals_path: str,
    bars_path: str,
    policy_config_path: str,
    grid_path: str,
    backtest_config_path: str,
    output_csv: str,
    max_workers: int = 4,
):
    """Run policy sweep in parallel with trade-level analysis."""
    LOGGER.info("Loading data...")
    signals = load_frame(signals_path)
    bars = load_frame(bars_path)
    
    with open(policy_config_path) as f:
        base_policy_config = json.load(f)
    
    with open(grid_path) as f:
        grid = yaml.safe_load(f)
    
    with open(backtest_config_path) as f:
        backtest_config = yaml.safe_load(f)
    
    param_sets = expand_parameter_grid(grid)
    total = len(param_sets)
    
    output_dir = Path(output_csv).parent / "trade_analyses"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    LOGGER.info(f"Running {total} configs with {max_workers} workers...")
    
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                run_single_config,
                sweep_id,
                overrides,
                signals,
                bars,
                base_policy_config,
                backtest_config,
                output_dir,
            ): sweep_id
            for sweep_id, overrides in enumerate(param_sets)
        }
        
        for future in as_completed(futures):
            sweep_id = futures[future]
            try:
                result = future.result()
                results.append(result)
                if len(results) % 10 == 0:
                    LOGGER.info(f"Completed {len(results)}/{total} configs")
            except Exception as e:
                LOGGER.error(f"Config {sweep_id} failed: {e}")
    
    # Save results
    df = pd.DataFrame(results)
    df.to_csv(output_csv, index=False)
    LOGGER.info(f"✅ Results saved to {output_csv}")
    LOGGER.info(f"✅ Trade analyses saved to {output_dir}")
    
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--signals", required=True)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--policy-config", required=True)
    parser.add_argument("--grid", required=True)
    parser.add_argument("--backtest-config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    parallel_sweep(
        args.signals,
        args.bars,
        args.policy_config,
        args.grid,
        args.backtest_config,
        args.output,
        args.workers,
    )


if __name__ == "__main__":
    main()
