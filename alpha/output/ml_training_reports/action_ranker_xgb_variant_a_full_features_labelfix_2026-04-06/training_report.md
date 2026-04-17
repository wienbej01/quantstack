# Action Ranker Training Report

- artifact: `alpha/models/action_ranker_xgb_variant_a_full_features_labelfix_2026-04-06.pkl`
- hold buckets: `[3, 5, 8, 12]`
- base edge bps: `8.0`
- spread weight: `0.35`
- positive edge buffer bps: `2.0`
- edge weight scale bps: `12.0`
- objective: `xgb_logistic`
- feature profile: `full`
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
- validation precision: `0.500`
- validation mean edge bps: `18.56`
- test selected: `16`
- test precision: `0.625`
- test mean edge bps: `34.29`

## Top Features

- mid_mean_30s: 0.0238
- mid_mean_10s: 0.0213
- spread_mean_10s: 0.0168
- micro_off_std_60s: 0.0162
- mid_mean_60s: 0.0152
- mid: 0.0143
- obi_5_std_300s: 0.0138
- spread_std_10s: 0.0121
- spread: 0.0121
- obi_5_std_60s: 0.0119
- pressure_k_mean_60s: 0.0113
- obi_5_std_30s: 0.0113
- microprice: 0.0111
- obi_1_std_30s: 0.0110
- spread_mean_60s: 0.0110
- depth_imb_k_std_60s: 0.0109
- seconds_since_open: 0.0106
- obi_1_std_10s: 0.0104
- spread_mean_30s: 0.0104
- micro_off_std_30s: 0.0104
