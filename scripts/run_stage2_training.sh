#!/bin/bash
set -e

cd /home/jacobw/quantstack

echo "Starting Stage 2 training at $(date)"
echo "Output directory: artefacts/extensions/intraday_ml/phaseA_full_sip_v2/bigmove_stage2_dir"
echo "="

python -u -m extensions.intraday_ml_models.train_bigmove_stage2_dir \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml \
  --output-root artefacts/extensions/intraday_ml/phaseA_full_sip_v2/bigmove_stage2_dir

echo "="
echo "Stage 2 training completed at $(date)"
