#!/bin/bash

cd /home/jacobw/quantstack

OUTPUT_ROOT="artefacts/extensions/intraday_ml/phaseA_full_sip_v2"
STAGE1_METADATA="$OUTPUT_ROOT/metadata.json"
CHECK_INTERVAL=30

echo "Waiting for Stage 1 to complete..."
echo "Checking for: $STAGE1_METADATA"
echo "Check interval: ${CHECK_INTERVAL}s"
echo ""

while true; do
    if [ -f "$STAGE1_METADATA" ]; then
        echo "Stage 1 completed! Metadata file found."
        echo ""
        
        # Display Stage 1 results
        echo "Stage 1 Results:"
        python -c "
import json
try:
    with open('$STAGE1_METADATA') as f:
        meta = json.load(f)
    print(f\"  Training samples: {meta['training_samples']:,}\")
    print(f\"  Feature count: {meta['feature_count']}\")
    
    metrics = meta['metrics']
    print(f\"  Accuracy: {metrics['accuracy']:.4f}\")
    print(f\"  ROC AUC: {metrics.get('roc_auc', 0):.4f}\")
    
    if 'feature_performance' in meta:
        perf = meta['feature_performance']
        stats = perf['correlation_stats']
        print(f\"  Max feature correlation: {stats['max_abs_correlation']:.4f}\")
        print(f\"  Features > 0.10: {stats['features_above_0.10']}\")
except Exception as e:
    print(f\"  Error reading metadata: {e}\")
"
        echo ""
        
        # Wait a bit to ensure file writes are complete
        sleep 5
        
        # Start Stage 2
        echo "Starting Stage 2 training..."
        exec /home/jacobw/quantstack/scripts/run_stage2_training.sh
        break
    fi
    
    # Show progress
    echo "$(date '+%H:%M:%S') - Still waiting... (Stage 1 running for $((SECONDS/60)) minutes)"
    sleep $CHECK_INTERVAL
done
