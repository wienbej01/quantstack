# Action Ranker Training Report

- artifact: `alpha/models/action_ranker_xgb_variant_a_full_any_labelfix_2026-04-06.pkl`
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
- cache source type: `any`
- split mode: `explicit_blocked`
- train block end: `2026-02-23`
- validation block end: `2026-03-09`
- causal price features: `False`
- validation top-k: `4`
- validation selected: `20`
- validation precision: `0.650`
- validation mean edge bps: `42.69`
- test selected: `16`
- test precision: `0.375`
- test mean edge bps: `-55.01`

## Top Features

- obi_5_std_300s: 0.0195
- depth_imb_k_mean_30s: 0.0141
- spread: 0.0138
- obi_5_std_30s: 0.0127
- depth_imb_k_std_60s: 0.0126
- micro_off_negative_30s: 0.0124
- spread_mean_60s: 0.0121
- obi_1_std_300s: 0.0117
- obi_5_std_10s: 0.0116
- depth_imb_k_std_300s: 0.0115
- depth_imb_k_mean_60s: 0.0112
- obi_5_std_60s: 0.0111
- obi_1_std_60s: 0.0110
- obi_1_std_30s: 0.0108
- depth_imb_negative_60s: 0.0107
- micro_off_negative_60s: 0.0101
- obi_5_mean_30s: 0.0100
- mid: 0.0098
- seconds_since_open: 0.0098
- pressure_k_delta_10s: 0.0098
