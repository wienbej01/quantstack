# Action Ranker Training Report

- artifact: `alpha/models/action_ranker_xgb_variant_b_stable_features_labelfix_2026-04-06.pkl`
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
- cache source type: `features`
- split mode: `explicit_blocked`
- train block end: `2026-02-23`
- validation block end: `2026-03-09`
- causal price features: `False`
- validation top-k: `4`
- validation selected: `4`
- validation precision: `0.750`
- validation mean edge bps: `52.24`
- test selected: `16`
- test precision: `0.250`
- test mean edge bps: `-10.02`

## Top Features

- mid: 0.0373
- spread_mean_10s: 0.0339
- spread: 0.0313
- spread_std_10s: 0.0300
- micro_off_negative_60s: 0.0293
- micro_off_std_60s: 0.0259
- spread_mean_60s: 0.0250
- pressure_k_std_10s: 0.0245
- seconds_since_open: 0.0230
- micro_off_std_10s: 0.0223
- obi_2: 0.0220
- micro_off_mean_10s: 0.0219
- microprice: 0.0217
- micro_off_negative_30s: 0.0212
- spread_std_60s: 0.0212
- micro_off_mean_60s: 0.0201
- depth_imb_negative_60s: 0.0200
- depth_imb_k_mean_60s: 0.0199
- depth_imb_k_std_10s: 0.0197
- depth_imb_k_std_60s: 0.0195
