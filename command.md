# Big-move pipeline commands (each CLI emits heartbeat logs every 60s)

 # 1. Train Stage 1 Model (Probability of Move)
python -m extensions.intraday_ml_models.train_bigmove_stage1 \
 --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
 --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
 --model-config configs/extensions/intraday_ml/model_bigmove_stage1.yaml \
 --output-root artefacts/extensions/intraday_ml/bigmove_stage1

 # 2. Train Stage 2 Model (Direction of Move)
python -m extensions.intraday_ml_models.train_bigmove_stage2_dir \
--dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
--targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
--model-config configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml \
--output-root artefacts/extensions/intraday_ml/bigmove_stage2_dir

# 3. Generate Out-of-Sample Scores
python -m extensions.intraday_ml.experiments.score_bigmove_oos \
--features artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
--baseline-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet \
--models-config configs/extensions/intraday_ml/bigmove_models_config.yaml \
--expected-r-floor 1.0 \
--output-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet

# 4. Run Policy Sweep
python -m extensions.intraday_ml.experiments.policy_sweep \
--policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
--grid configs/extensions/intraday_ml/policy_sweep_grid.yaml \
--backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
--output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier.csv

