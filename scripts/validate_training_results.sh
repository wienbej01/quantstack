#!/bin/bash
set -e

cd /home/jacobw/quantstack

OUTPUT_ROOT="artefacts/extensions/intraday_ml/phaseA_full_sip_v2"

echo "========================================================================"
echo "Training Validation Pipeline"
echo "========================================================================"
echo ""

# Check if training completed
if [ ! -f "$OUTPUT_ROOT/metadata.json" ]; then
    echo "ERROR: Stage 1 training not complete (metadata.json not found)"
    exit 1
fi

if [ ! -f "$OUTPUT_ROOT/bigmove_stage2_dir/metadata.json" ]; then
    echo "ERROR: Stage 2 training not complete (metadata.json not found)"
    exit 1
fi

echo "✓ Both training stages completed"
echo ""

# Display training results
echo "========================================================================"
echo "Stage 1: Probability Model Results"
echo "========================================================================"
python scripts/monitor_training.py | grep -A 30 "Stage 1"
echo ""

echo "========================================================================"
echo "Stage 2: Direction Model Results"
echo "========================================================================"
python scripts/monitor_training.py | grep -A 30 "Stage 2"
echo ""

# Generate OOS predictions
echo "========================================================================"
echo "Generating OOS Predictions"
echo "========================================================================"

if [ ! -f "$OUTPUT_ROOT/oos_predictions_bigmove.parquet" ]; then
    echo "Generating predictions..."
    python -m extensions.intraday_ml.experiments.score_bigmove_oos \
      --features "$OUTPUT_ROOT/oos_features.parquet" \
      --baseline-signals "$OUTPUT_ROOT/oos_predictions.parquet" \
      --models-config configs/extensions/intraday_ml/bigmove_models_config.yaml \
      --expected-r-floor 1.0 \
      --output-signals "$OUTPUT_ROOT/oos_predictions_bigmove.parquet"
    echo "✓ Predictions generated"
else
    echo "✓ Predictions already exist"
fi
echo ""

# Analyze predictions
echo "========================================================================"
echo "Prediction Analysis"
echo "========================================================================"
python scripts/analyze_predictions.py --predictions "$OUTPUT_ROOT/oos_predictions_bigmove.parquet"
echo ""

# Run backtest
echo "========================================================================"
echo "Running Backtest"
echo "========================================================================"
python scripts/run_backtest_1m.py
echo ""

echo "========================================================================"
echo "Validation Complete"
echo "========================================================================"
echo ""
echo "Review results and check:"
echo "  1. Feature correlations > 0.10"
echo "  2. Prediction distribution: 60-70% neutral, 15-20% long/short"
echo "  3. Target hit rate > 40%"
echo "  4. Positive PnL"
