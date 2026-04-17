# Action Ranker Training Report

- artifact: `alpha/models/action_ranker_xgb_variant_d_stable_causal_noside_features_2026-04-06.pkl`
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
- validation precision: `0.000`
- validation mean edge bps: `nan`
- test selected: `16`
- test precision: `0.000`
- test mean edge bps: `nan`

## Top Features

- mid: 0.0000
- spread: 0.0000
- microprice: 0.0000
- micro_off: 0.0000
- depth_bid_k: 0.0000
- depth_ask_k: 0.0000
- depth_imb_k: 0.0000
- pressure_k: 0.0000
- obi_1: 0.0000
- obi_2: 0.0000
- obi_3: 0.0000
- obi_5: 0.0000
- obi_10: 0.0000
- d_mid_5s: 0.0000
- d_spread_5s: 0.0000
- d_obi_1_5s: 0.0000
- d_micro_off_5s: 0.0000
- d_mid_30s: 0.0000
- d_spread_30s: 0.0000
- d_obi_1_30s: 0.0000
