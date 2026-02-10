# AAA Discovery Diagnostics

- Date range: 2024-01-01 to 2024-12-31
- Horizons: 30, 60, 90, 120, 180
- Current regime: bear_low_vol
- Require event-based: True
- Overfit policy: reject
- Min AAA score: 0.02
- Validation cost (bps): 2.0
- Min net expectancy (bps): 1.0
- Dedupe by symbol/day: False (first)
- Validation enabled: True

## Totals
- Segments: 40
- Raw patterns: 7372
- Pass event filter: 3123
- Pass overfit filter: 6676
- Pass regime filter: 7372
- Pass AAA score: 4721
- Pass AAA filters: 2072
- Pass validation: 317

## Top Overfit Rejections
- 2: Expectancy too high (13.102% > 10.000%)
- 2: Expectancy too high (17.440% > 10.000%)
- 2: Expectancy too high (10.578% > 10.000%)
- 2: Expectancy too high (10.572% > 10.000%)
- 2: Expectancy too high (15.939% > 10.000%)
- 2: Expectancy too high (16.674% > 10.000%)
- 1: Expectancy too high (21.685% > 10.000%)
- 1: Expectancy too high (16.341% > 10.000%)
- 1: Expectancy too high (12.073% > 10.000%)
- 1: Expectancy too high (11.351% > 10.000%)
- 1: Expectancy too high (11.814% > 10.000%)
- 1: Expectancy too high (10.026% > 10.000%)
- 1: Expectancy too high (11.471% > 10.000%)
- 1: Expectancy too high (10.786% > 10.000%)
- 1: Expectancy too high (10.815% > 10.000%)
- 1: Expectancy too high (15.845% > 10.000%)
- 1: Expectancy too high (16.554% > 10.000%)
- 1: Expectancy too high (14.651% > 10.000%)
- 1: Expectancy too high (16.220% > 10.000%)
- 1: Expectancy too high (22.599% > 10.000%)

## Top Validation Rejections
- 316: PASS
- 4: Net expectancy -0.264% < 1.000% after 2.0 bps cost
- 4: Net expectancy -2.004% < 1.000% after 2.0 bps cost
- 4: Net expectancy -2.415% < 1.000% after 2.0 bps cost
- 4: Net expectancy -1.927% < 1.000% after 2.0 bps cost
- 3: Net expectancy -2.736% < 1.000% after 2.0 bps cost
- 3: Sharpe dropped 47.0% (limit: 40.0%)
- 2: Net expectancy -0.707% < 1.000% after 2.0 bps cost
- 2: Net expectancy -0.087% < 1.000% after 2.0 bps cost
- 2: Net expectancy -1.131% < 1.000% after 2.0 bps cost
- 2: Net expectancy -1.807% < 1.000% after 2.0 bps cost
- 2: Net expectancy -0.343% < 1.000% after 2.0 bps cost
- 2: Net expectancy -2.908% < 1.000% after 2.0 bps cost
- 2: Net expectancy -4.967% < 1.000% after 2.0 bps cost
- 2: Net expectancy -4.082% < 1.000% after 2.0 bps cost
- 2: Net expectancy -5.315% < 1.000% after 2.0 bps cost
- 2: Net expectancy -1.080% < 1.000% after 2.0 bps cost
- 2: Net expectancy -1.385% < 1.000% after 2.0 bps cost
- 2: Net expectancy -1.663% < 1.000% after 2.0 bps cost
- 2: Expectancy dropped 55.8% (limit: 50.0%)
