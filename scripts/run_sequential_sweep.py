"""Sequential policy sweep with robust error handling and logging."""
import sys
import logging
import json
from pathlib import Path
import pandas as pd
import yaml
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('reports/sequential_sweep.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Import after logging setup
from extensions.intraday_ml.experiments.policy_sweep import (
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


def run_single_config(
    sweep_id: int,
    overrides: dict,
    signals: pd.DataFrame,
    bars: pd.DataFrame,
    base_policy_config: dict,
    backtest_config: dict,
    output_dir: Path,
) -> dict:
    """Run a single configuration."""
    logger.info(f"Running config {sweep_id}/{len(param_sets)}")
    logger.debug(f"  Overrides: {overrides}")
    
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
        
        logger.debug(f"  Orders: {len(orders)}, Rejections: {len(rejections)}")
        
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
            
            # Save trades
            trades_path = output_dir / f"trades_config_{sweep_id:04d}.parquet"
            trades_df.to_parquet(trades_path, index=False)
            logger.debug(f"  Saved trades to {trades_path}")
            
            # Analyze trades
            try:
                analyzer = TradeAnalyzer(trades_df, sweep_id, overrides)
                analysis = analyzer.analyze()
                
                analysis_path = output_dir / f"analysis_config_{sweep_id:04d}.json"
                with open(analysis_path, 'w') as f:
                    json.dump(analysis, f, indent=2, default=str)
                logger.debug(f"  Saved analysis to {analysis_path}")
            except Exception as e:
                logger.warning(f"  Trade analysis failed: {e}")
        
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
        
        logger.info(f"  ✓ Config {sweep_id}: {trade_count} trades, WR={hit_rate:.1%}, AvgR={avg_r:.2f}")
        return row
        
    except Exception as e:
        logger.error(f"  ✗ Config {sweep_id} failed: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return {
            "sweep_id": sweep_id,
            "error": str(e),
            "entries": 0,
            "rejections": 0,
        }


if __name__ == "__main__":
    logger.info("=== Sequential Policy Sweep ===")
    logger.info(f"Start time: {datetime.now()}")
    
    # Load data
    logger.info("Loading data...")
    signals = pd.read_parquet("artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet")
    bars = pd.read_parquet("artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet")
    logger.info(f"  Signals: {len(signals)}, Bars: {len(bars)}")
    
    # Load configs
    with open("configs/extensions/intraday_ml/policy_config_bigmove_simple.json") as f:
        base_policy_config = json.load(f)
    
    with open("configs/extensions/intraday_ml/policy_sweep_grid_v2.yaml") as f:
        grid = yaml.safe_load(f)
    
    backtest_config = {}
    
    # Generate parameter sets
    param_sets = expand_parameter_grid(grid)
    total = len(param_sets)
    logger.info(f"Testing {total} configurations")
    
    # Create output directory
    output_dir = Path("artefacts/extensions/intraday_ml/policy_sweeps_v4")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "trade_analyses").mkdir(exist_ok=True)
    
    # Run sweep
    results = []
    for sweep_id, overrides in enumerate(param_sets):
        result = run_single_config(
            sweep_id,
            overrides,
            signals,
            bars,
            base_policy_config,
            backtest_config,
            output_dir / "trade_analyses",
        )
        results.append(result)
        
        # Save intermediate results every 50 configs
        if (sweep_id + 1) % 50 == 0:
            df_temp = pd.DataFrame(results)
            df_temp.to_csv(output_dir / "results_partial.csv", index=False)
            logger.info(f"  Saved partial results ({sweep_id + 1}/{total})")
    
    # Save final results
    df = pd.DataFrame(results)
    df.to_csv(output_dir / "results.csv", index=False)
    logger.info(f"✅ Results saved to {output_dir / 'results.csv'}")
    
    # Summary
    logger.info("\n=== Summary ===")
    logger.info(f"Total configs: {len(df)}")
    logger.info(f"Successful: {(df['entries'] > 0).sum()}")
    logger.info(f"Failed: {(df.get('error', pd.Series()).notna()).sum()}")
    
    if (df['entries'] > 0).any():
        success_df = df[df['entries'] > 0]
        logger.info(f"\nPerformance:")
        logger.info(f"  Unique win rates: {success_df['metric_win_rate'].nunique()}")
        logger.info(f"  Unique trade counts: {success_df['metric_total_trades'].nunique()}")
        logger.info(f"  Win rate range: {success_df['metric_win_rate'].min():.1%} to {success_df['metric_win_rate'].max():.1%}")
        logger.info(f"  Trade count range: {int(success_df['metric_total_trades'].min())} to {int(success_df['metric_total_trades'].max())}")
        logger.info(f"  Sharpe range: {success_df['metric_sharpe_ratio'].min():.2f} to {success_df['metric_sharpe_ratio'].max():.2f}")
    
    logger.info(f"\nEnd time: {datetime.now()}")
