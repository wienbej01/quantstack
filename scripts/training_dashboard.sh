#!/bin/bash

cd /home/jacobw/quantstack

OUTPUT_ROOT="artefacts/extensions/intraday_ml/phaseA_full_sip_v2"

clear
echo "========================================================================"
echo "Training Dashboard - $(date)"
echo "========================================================================"
echo ""

# Check processes
echo "Running Processes:"
echo "------------------------------------------------------------"
STAGE1_PID=$(pgrep -f "train_bigmove_stage1.*phaseA_full_sip_v2" || echo "")
STAGE2_PID=$(pgrep -f "train_bigmove_stage2_dir.*phaseA_full_sip_v2" || echo "")
WAIT_PID=$(pgrep -f "wait_and_run_stage2" || echo "")

if [ -n "$STAGE1_PID" ]; then
    RUNTIME=$(($(date +%s) - $(stat -c %Y /proc/$STAGE1_PID 2>/dev/null || echo $(date +%s))))
    echo "  ✓ Stage 1 Training (PID $STAGE1_PID) - Running for $((RUNTIME/60)) minutes"
else
    echo "  ✗ Stage 1 Training - Not running"
fi

if [ -n "$STAGE2_PID" ]; then
    RUNTIME=$(($(date +%s) - $(stat -c %Y /proc/$STAGE2_PID 2>/dev/null || echo $(date +%s))))
    echo "  ✓ Stage 2 Training (PID $STAGE2_PID) - Running for $((RUNTIME/60)) minutes"
else
    echo "  ✗ Stage 2 Training - Not running"
fi

if [ -n "$WAIT_PID" ]; then
    echo "  ✓ Stage 2 Auto-Starter (PID $WAIT_PID) - Waiting"
else
    echo "  ✗ Stage 2 Auto-Starter - Not running"
fi

echo ""

# Check files
echo "Output Files:"
echo "------------------------------------------------------------"
python scripts/monitor_training.py 2>/dev/null | grep -A 20 "File Status:"

echo ""

# Stage 1 progress
if [ -f "$OUTPUT_ROOT/metadata.json" ]; then
    echo "Stage 1 Results:"
    echo "------------------------------------------------------------"
    python -c "
import json
with open('$OUTPUT_ROOT/metadata.json') as f:
    meta = json.load(f)
print(f\"  Samples: {meta['training_samples']:,}  Features: {meta['feature_count']}\")
metrics = meta['metrics']
print(f\"  Accuracy: {metrics['accuracy']:.4f}  ROC AUC: {metrics.get('roc_auc', 0):.4f}\")
if 'feature_performance' in meta:
    perf = meta['feature_performance']
    stats = perf['correlation_stats']
    print(f\"  Max Correlation: {stats['max_abs_correlation']:.4f}  Features>0.10: {stats['features_above_0.10']}\")
" 2>/dev/null
    echo ""
fi

# Stage 2 progress
if [ -f "$OUTPUT_ROOT/bigmove_stage2_dir/metadata.json" ]; then
    echo "Stage 2 Results:"
    echo "------------------------------------------------------------"
    python -c "
import json
with open('$OUTPUT_ROOT/bigmove_stage2_dir/metadata.json') as f:
    meta = json.load(f)
print(f\"  Samples: {meta['training_samples']:,}  Features: {meta['feature_count']}\")
metrics = meta['metrics']
print(f\"  Accuracy: {metrics['accuracy']:.4f}  ROC AUC: {metrics.get('roc_auc', 0):.4f}\")
if 'feature_performance' in meta:
    perf = meta['feature_performance']
    stats = perf['correlation_stats']
    print(f\"  Max Correlation: {stats['max_abs_correlation']:.4f}  Features>0.10: {stats['features_above_0.10']}\")
" 2>/dev/null
    echo ""
fi

# Recent log activity
echo "Recent Log Activity:"
echo "------------------------------------------------------------"
echo "Stage 1:"
grep -v "heartbeat" /tmp/stage1_training_full.log 2>/dev/null | tail -3 | sed 's/^/  /'
echo ""
echo "Stage 2:"
tail -3 /tmp/stage2_training_full.log 2>/dev/null | sed 's/^/  /'

echo ""
echo "========================================================================"
echo "Refresh: watch -n 30 $0"
