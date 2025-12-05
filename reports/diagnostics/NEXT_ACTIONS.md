# Next Actions Checklist

## ⏳ Currently Running
- **Step 2:** Stage 2 directional model training (in progress)
- **Do not interrupt** - Let it complete

## ✅ Completed While Waiting
1. Stage 1 feature importance analysis → `reports/diagnostics/stage1_analysis.json`
2. Training metadata analysis → `reports/diagnostics/training_meta_analysis.json`
3. Label distribution analysis → `reports/diagnostics/label_analysis.json`
4. Diagnostic summary report → `reports/diagnostics/DIAGNOSTIC_SUMMARY.md`

## 📋 After Step 2 Completes

### Immediate (5 minutes)
```bash
# 1. Check Stage 2 output
ls -lh artefacts/extensions/intraday_ml/bigmove_stage2_dir/
cat artefacts/extensions/intraday_ml/bigmove_stage2_dir/train_meta.json

# 2. Run Stage 2 diagnostics
python extensions/intraday_ml/diagnostics/analyze_stage1.py \
  --model-path artefacts/extensions/intraday_ml/bigmove_stage2_dir/model.pkl \
  --output reports/diagnostics/stage2_analysis.json

# 3. Run Step 3 (OOS scoring)
python -m extensions.intraday_ml.experiments.score_bigmove_oos \
  --features artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
  --baseline-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet \
  --models-config configs/extensions/intraday_ml/bigmove_models_config.yaml \
  --expected-r-floor 1.0 \
  --output-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet
```

### After Step 3 (10 minutes)
```bash
# 4. Analyze signal frequency
python extensions/intraday_ml/diagnostics/analyze_signal_frequency.py

# 5. Run Step 4 (Policy sweep)
python -m extensions.intraday_ml.experiments.policy_sweep \
  --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
  --grid configs/extensions/intraday_ml/policy_sweep_grid.yaml \
  --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
  --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier.csv
```

### After Step 4 (Analysis)
```bash
# 6. Review sweep results
cat artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier.csv | column -t -s,

# 7. Identify best configuration
# Look for: Sharpe > 1.5, Win Rate > 45%, Max DD < 15%
```

## 🎯 Key Questions to Answer

### From Signal Frequency Analysis
- [ ] How many signals/day at prob > 0.70?
- [ ] Is there enough signal volume for 3-5 trades/day?
- [ ] Are signals clustered in time or distributed?

### From Stage 2 Performance
- [ ] What is directional accuracy? (Need > 55%)
- [ ] Is Stage 2 training set too small? (Only trains on big moves)
- [ ] Do long and short predictions have similar accuracy?

### From Policy Sweep
- [ ] What is best Sharpe ratio achieved?
- [ ] What thresholds produce 3-5 trades/day?
- [ ] How sensitive is performance to threshold changes?
- [ ] What is win rate at optimal thresholds?

## 🚨 Red Flags to Watch For

1. **Stage 2 accuracy < 55%:** Directional model is no better than coin flip
2. **Signal frequency < 3/day at prob > 0.70:** Not enough opportunities
3. **Signal frequency > 10/day at prob > 0.70:** Too noisy, need tighter threshold
4. **Sweep Sharpe < 1.0:** System not viable without major changes
5. **Win rate < 40% with 1:2 R:R:** Losing too often

## 📊 Files Created

### Diagnostic Scripts
- `extensions/intraday_ml/diagnostics/analyze_stage1.py`
- `extensions/intraday_ml/diagnostics/analyze_training_meta.py`
- `extensions/intraday_ml/diagnostics/analyze_labels.py`
- `extensions/intraday_ml/diagnostics/analyze_signal_frequency.py`

### Reports
- `reports/diagnostics/stage1_analysis.json` + `.csv`
- `reports/diagnostics/training_meta_analysis.json`
- `reports/diagnostics/label_analysis.json`
- `reports/diagnostics/DIAGNOSTIC_SUMMARY.md`
- `reports/diagnostics/NEXT_ACTIONS.md` (this file)

### Pending (After Step 3)
- `reports/diagnostics/signal_frequency.json` + `.csv`
- `reports/diagnostics/stage2_analysis.json` + `.csv`

## 💡 Quick Wins for Next Iteration

If initial results are promising (Sharpe > 1.0), prepare these enhancements:

1. **Config files for tighter thresholds:**
   ```yaml
   # policy_config_bigmove_selective.json
   stage1_threshold: 0.70  # up from 0.60
   stage2_threshold: 0.65  # up from 0.60
   max_trades_per_day: 5
   ```

2. **Ranking mechanism in BigMovePolicy:**
   - Score = (prob - 0.5) * 2 * (atr / price)
   - Pick top 5 scores each decision window

3. **Cost model in backtest:**
   - Commission: $1.00 per trade
   - Slippage: 4 bps
   - Min profit target: 2.5 ATR (up from 2.0)

---

**Last Updated:** 2025-12-04 10:55 SGT
**Status:** Waiting for Step 2 to complete
