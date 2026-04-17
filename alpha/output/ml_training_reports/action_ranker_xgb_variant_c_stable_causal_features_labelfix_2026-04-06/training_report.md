# Action Ranker Training Report

- artifact: `alpha/models/action_ranker_xgb_variant_c_stable_causal_features_labelfix_2026-04-06.pkl`
- hold buckets: `[3, 5, 8, 12]`
- base edge bps: `8.0`
- spread weight: `0.35`
- positive edge buffer bps: `2.0`
- edge weight scale bps: `12.0`
- objective: `xgb_logistic`
- feature profile: `stable_causal`
- train window start: `2025-12-19`
- train window end: `2026-03-13`
- business days only: `True`
- cache source type: `features`
- split mode: `explicit_blocked`
- train block end: `2026-02-23`
- validation block end: `2026-03-09`
- causal price features: `True`
- validation top-k: `4`
- validation selected: `4`
- validation precision: `0.750`
- validation mean edge bps: `46.59`
- test selected: `16`
- test precision: `0.500`
- test mean edge bps: `14.48`

## Top Features

- dist_vwap_bps: 0.0358
- spread_mean_10s: 0.0291
- mid: 0.0277
- micro_off_negative_60s: 0.0275
- spread: 0.0231
- micro_off_negative_30s: 0.0214
- spread_mean_60s: 0.0203
- spread_std_10s: 0.0202
- atr_pct: 0.0192
- microprice: 0.0191
- obi_2: 0.0185
- micro_off_std_10s: 0.0185
- session_progress: 0.0182
- spread_std_60s: 0.0179
- micro_off_mean_10s: 0.0178
- depth_imb_k_mean_60s: 0.0177
- log_log_ret_5: 0.0167
- pressure_k_mean_60s: 0.0163
- hl_range_pct: 0.0157
- pressure_k_std_10s: 0.0156
