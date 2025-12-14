#!/usr/bin/env python3
"""Run complete enhanced pipeline with all recommendations."""

import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def run_script(script_name, description):
    """Run a script and return success status."""
    logging.info(f"\n{'='*60}")
    logging.info(f"PHASE: {description}")
    logging.info(f"{'='*60}")

    script_path = Path("scripts") / script_name
    if not script_path.exists():
        logging.error(f"Script not found: {script_path}")
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=False,
            text=True,
            check=True,
        )
        logging.info(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ {description} failed with exit code {e.returncode}")
        return False
    except Exception as e:
        logging.error(f"❌ {description} failed: {e}")
        return False


def main():
    logging.info("=" * 80)
    logging.info("ENHANCED PIPELINE: All Recommendations Implementation")
    logging.info("=" * 80)
    logging.info("Enhancements:")
    logging.info("✅ Multi-timeframe features (5m aggregates)")
    logging.info("✅ Session context features (gap fill, range)")
    logging.info("✅ Improved ICT features (multi-bar patterns)")
    logging.info("✅ Enhanced VPA features (cumulative delta)")
    logging.info("✅ Market context (SPY correlation)")
    logging.info("✅ XGBoost with Optuna hyperparameter tuning")
    logging.info("✅ SHAP-based feature selection")
    logging.info("✅ Longer exit horizons (10, 15, 30 bars)")
    logging.info("✅ Multi-class labels")
    logging.info("✅ Regime detection")
    logging.info("✅ Shorter training window (3 months)")
    logging.info("✅ Purging between splits")

    # Phase 1: Build enhanced features
    success = run_script(
        "build_enhanced_features.py",
        "Phase 1: Build Enhanced Features (Multi-timeframe + ICT + VPA + SPY)",
    )
    if not success:
        logging.error("Pipeline failed at Phase 1")
        return False

    # Phase 2: Train enhanced models
    success = run_script(
        "train_enhanced_model.py",
        "Phase 2: Train Enhanced Models (XGBoost + Optuna + SHAP)",
    )
    if not success:
        logging.error("Pipeline failed at Phase 2")
        return False

    logging.info("\n" + "=" * 80)
    logging.info("🎉 ENHANCED PIPELINE COMPLETED SUCCESSFULLY")
    logging.info("=" * 80)
    logging.info("Results available in:")
    logging.info("  - run/enhanced_features/features.parquet")
    logging.info("  - run/enhanced_results/metrics.csv")
    logging.info("  - run/enhanced_results/trades.csv")

    # Show expected improvements
    logging.info("\n📈 EXPECTED IMPROVEMENTS:")
    logging.info("  - Feature Quality: 35 → 50+ features with better correlations")
    logging.info("  - Model Performance: AUC 0.59 → 0.65+ (target 0.70+)")
    logging.info("  - Win Rate: 46.9% → 52%+ (target 55%+)")
    logging.info("  - Profitability: -$1,538 → Positive expectancy")
    logging.info("  - Robustness: Regime detection + purged validation")

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
