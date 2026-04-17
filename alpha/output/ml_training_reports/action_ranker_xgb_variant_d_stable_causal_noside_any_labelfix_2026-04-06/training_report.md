# Action Ranker Training Report

- artifact: `alpha/models/action_ranker_xgb_variant_d_stable_causal_noside_any_labelfix_2026-04-06.pkl`
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
- cache source type: `any`
- split mode: `explicit_blocked`
- train block end: `2026-02-23`
- validation block end: `2026-03-09`
- causal price features: `True`
- validation top-k: `4`
- validation selected: `20`
- validation precision: `0.550`
- validation mean edge bps: `26.72`
- test selected: `16`
- test precision: `0.438`
- test mean edge bps: `-27.09`

## Top Features

- spread: 0.0288
- depth_imb_k_std_60s: 0.0237
- micro_off_negative_60s: 0.0221
- atr_pct: 0.0221
- dist_vwap_bps: 0.0213
- spread_mean_60s: 0.0205
- mid: 0.0197
- micro_off_negative_30s: 0.0191
- session_progress: 0.0188
- hl_range_pct: 0.0187
- microprice: 0.0183
- spread_std_10s: 0.0172
- position_in_range: 0.0168
- depth_imb_k_mean_10s: 0.0165
- pressure_k_std_60s: 0.0165
- pressure_k_std_10s: 0.0163
- micro_off_std_10s: 0.0162
- spread_mean_10s: 0.0161
- depth_imb_positive_10s: 0.0159
- seconds_since_open: 0.0158
