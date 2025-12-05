#!/bin/bash
set -e

cd /home/jacobw/quantstack

echo "Starting Stage 1 training at $(date)"
echo "Output directory: artefacts/extensions/intraday_ml/phaseA_full_sip_v2"
echo "="

python -u -m extensions.intraday_ml_models.train_bigmove_stage1 \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage1.yaml \
  --output-root artefacts/extensions/intraday_ml/phaseA_full_sip_v2

echo "="
echo "Stage 1 training completed at $(date)"
