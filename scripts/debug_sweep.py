"""Debug script to test sweep components individually."""
import json
import logging
import sys

import pandas as pd

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

def test_load_data():
    """Test data loading."""
    logger.info("=== Testing Data Loading ===")
    try:
        signals = pd.read_parquet("artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet")
        logger.info(f"✓ Signals loaded: {len(signals)} rows, {len(signals.columns)} columns")
        logger.info(f"  Columns: {signals.columns.tolist()}")
        
        bars = pd.read_parquet("artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet")
        logger.info(f"✓ Bars loaded: {len(bars)} rows, {len(bars.columns)} columns")
        
        return signals, bars
    except Exception as e:
        logger.error(f"✗ Data loading failed: {e}")
        raise

def test_policy_config():
    """Test policy config loading."""
    logger.info("\n=== Testing Policy Config ===")
    try:
        with open("configs/extensions/intraday_ml/policy_config_bigmove_simple.json") as f:
            config = json.load(f)
        logger.info("✓ Policy config loaded")
        logger.info(f"  bigmove_policy.probability_threshold: {config.get('bigmove_policy', {}).get('probability_threshold')}")
        logger.info(f"  prob_threshold_long: {config.get('prob_threshold_long')}")
        logger.info(f"  tod_filter_enabled: {config.get('tod_filter_enabled')}")
        return config
    except Exception as e:
        logger.error(f"✗ Policy config loading failed: {e}")
        raise

def test_policy_creation(config):
    """Test policy instantiation."""
    logger.info("\n=== Testing Policy Creation ===")
    try:
        from extensions.intraday_ml_policies.intraday_ml_decision_policy import (
            IntradayMLDecisionPolicy,
        )
        policy = IntradayMLDecisionPolicy(config)
        logger.info(f"✓ Policy created: {type(policy).__name__}")
        return policy
    except Exception as e:
        logger.error(f"✗ Policy creation failed: {e}")
        import traceback
        traceback.print_exc()
        raise

def test_signal_processing(policy, signals, bars):
    """Test signal processing."""
    logger.info("\n=== Testing Signal Processing ===")
    try:
        # Take small sample
        sample_signals = signals.head(100).copy()
        logger.info(f"Processing {len(sample_signals)} sample signals")
        
        # Check required columns
        if hasattr(policy, 'get_required_feature_columns'):
            required = policy.get_required_feature_columns()
            logger.info(f"  Required columns: {required}")
            
            missing = required - set(sample_signals.columns)
            if missing:
                logger.warning(f"  Missing columns: {missing}")
                # Add from bars
                for col in missing:
                    if col in bars.columns:
                        sample_signals = sample_signals.merge(
                            bars[['ts', 'symbol', col]],
                            on=['ts', 'symbol'],
                            how='left'
                        )
                        logger.info(f"    Added {col} from bars")
        
        orders, rejections = policy.process_signals(sample_signals)
        logger.info("✓ Signal processing complete")
        logger.info(f"  Orders: {len(orders)}")
        logger.info(f"  Rejections: {len(rejections)}")
        
        if len(orders) > 0:
            logger.info(f"  Order columns: {orders.columns.tolist()}")
        
        rejection_counts = policy.get_rejection_reason_counts()
        logger.info(f"  Rejection reasons: {dict(rejection_counts)}")
        
        return orders, rejections
    except Exception as e:
        logger.error(f"✗ Signal processing failed: {e}")
        import traceback
        traceback.print_exc()
        raise

def test_backtest(bars, orders):
    """Test backtest execution."""
    logger.info("\n=== Testing Backtest ===")
    try:
        from extensions.intraday_ml.backtest import intraday_ml_run_backtest
        
        if len(orders) == 0:
            logger.warning("No orders to backtest")
            return None
        
        logger.info(f"Running backtest with {len(orders)} orders")
        artifacts = intraday_ml_run_backtest(bars, orders, cfg={})
        
        logger.info("✓ Backtest complete")
        logger.info(f"  Artifacts keys: {artifacts.keys()}")
        
        trades = artifacts.get('trades')
        if trades is not None and not trades.empty:
            logger.info(f"  Trades: {len(trades)}")
            logger.info(f"  Trade columns: {trades.columns.tolist()}")
            logger.info(f"  Sample trade:\n{trades.head(1).T}")
        else:
            logger.warning("  No trades generated")
        
        metrics = artifacts.get('metrics', {})
        logger.info(f"  Metrics: {metrics}")
        
        return artifacts
    except Exception as e:
        logger.error(f"✗ Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        raise

def main():
    """Run all tests."""
    try:
        signals, bars = test_load_data()
        config = test_policy_config()
        policy = test_policy_creation(config)
        orders, rejections = test_signal_processing(policy, signals, bars)
        artifacts = test_backtest(bars, orders)
        
        logger.info("\n=== All Tests Passed ===")
        return True
    except Exception as e:
        logger.error("\n=== Tests Failed ===")
        logger.error(f"Error: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
