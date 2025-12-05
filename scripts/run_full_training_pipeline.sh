#!/bin/bash
set -e

cd /home/jacobw/quantstack

OUTPUT_ROOT="artefacts/extensions/intraday_ml/phaseA_full_sip_v2"

echo "========================================================================"
echo "Full Training Pipeline Started at $(date)"
echo "========================================================================"

# Stage 1: Probability Model
echo ""
echo "Stage 1: Training big-move probability model..."
python -u -m extensions.intraday_ml_models.train_bigmove_stage1 \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage1.yaml \
  --output-root "$OUTPUT_ROOT"

echo ""
echo "Stage 1 completed at $(date)"
echo ""

# Check Stage 1 results
if [ -f "$OUTPUT_ROOT/metadata.json" ]; then
    echo "Stage 1 Feature Performance:"
    python -c "
import json
with open('$OUTPUT_ROOT/feature_performance_summary.json') as f:
    perf = json.load(f)
    stats = perf['correlation_stats']
    print(f\"  Max correlation: {stats['max_abs_correlation']:.4f}\")
    print(f\"  Features > 0.10: {stats['features_above_0.10']}\")
    print(f\"  Features > 0.05: {stats['features_above_0.05']}\")
" 2>/dev/null || echo "  (Feature performance file not found)"
fi

# Stage 2: Direction Model
echo ""
echo "Stage 2: Training direction classifier..."
python -u -m extensions.intraday_ml_models.train_bigmove_stage2_dir \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml \
  --output-root "$OUTPUT_ROOT/bigmove_stage2_dir"

echo ""
echo "Stage 2 completed at $(date)"
echo ""

# Check Stage 2 results
if [ -f "$OUTPUT_ROOT/bigmove_stage2_dir/metadata.json" ]; then
    echo "Stage 2 Feature Performance:"
    python -c "
import json
with open('$OUTPUT_ROOT/bigmove_stage2_dir/feature_performance_summary.json') as f:
    perf = json.load(f)
    stats = perf['correlation_stats']
    print(f\"  Max correlation: {stats['max_abs_correlation']:.4f}\")
    print(f\"  Features > 0.10: {stats['features_above_0.10']}\")
    print(f\"  Features > 0.05: {stats['features_above_0.05']}\")
" 2>/dev/null || echo "  (Feature performance file not found)"
fi

echo ""
echo "========================================================================"
echo "Full Training Pipeline Completed at $(date)"
echo "========================================================================"
echo ""
echo "Next steps:"
echo "  1. Review feature performance: python scripts/monitor_training.py"
echo "  2. Generate predictions: python -m extensions.intraday_ml.experiments.score_bigmove_oos"
echo "  3. Run backtest: python scripts/run_backtest_1m.py"
