# Action Ranker Training Report

- artifact: `alpha/models/action_ranker_xgb_variant_b_stable_any_labelfix_2026-04-06.pkl`
- hold buckets: `[3, 5, 8, 12]`
- base edge bps: `8.0`
- spread weight: `0.35`
- positive edge buffer bps: `2.0`
- edge weight scale bps: `12.0`
- objective: `xgb_logistic`
- feature profile: `stable`
- train window start: `2025-12-19`
- train window end: `2026-03-13`
- business days only: `True`
- cache source type: `any`
- split mode: `explicit_blocked`
- train block end: `2026-02-23`
- validation block end: `2026-03-09`
- causal price features: `False`
- validation top-k: `4`
- validation selected: `20`
- validation precision: `0.450`
- validation mean edge bps: `-35.79`
- test selected: `16`
- test precision: `0.562`
- test mean edge bps: `-8.75`

## Top Features

- spread: 0.0360
- depth_imb_k_std_60s: 0.0277
- spread_mean_60s: 0.0275
- micro_off_negative_60s: 0.0272
- mid: 0.0255
- micro_off_negative_30s: 0.0242
- micro_off_std_60s: 0.0227
- microprice: 0.0227
- seconds_since_open: 0.0226
- pressure_k_std_60s: 0.0223
- depth_imb_negative_60s: 0.0222
- spread_std_10s: 0.0213
- micro_off_std_10s: 0.0210
- pressure_k_std_10s: 0.0208
- spread_mean_10s: 0.0206
- depth_imb_k_mean_60s: 0.0204
- spread_std_60s: 0.0197
- depth_imb_positive_60s: 0.0194
- depth_imb_positive_10s: 0.0194
- depth_imb_k_mean_10s: 0.0192
