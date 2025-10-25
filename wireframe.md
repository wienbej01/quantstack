Data lake (read-only)

Bronze: raw vendor files (polygon). QA deferred.

Silver: normalized typings/timezones.

Gold: canonical bars, sessionized partitions. Mounted at /home/jacobw/gcs-mount/gold.

Core libs

qx-core/

schemas.py required table schemas (bars, signals, orders, fills, trades, metrics, inputs_checksum, risk_rejects, allocation_log).

validators.py schema checks.

hashers.py normalized dataframe hashing (UTC ns, sorted, stable dtypes).

utils.py time/session utils.

qx-data/

gold_loader.py read-only loader returning canonical bars: [ts(UTC ns), symbol, open, high, low, close, volume, (opt) vwap, trades].

qx-features/

core_basics.py VWAP, relative volume, ATR with warmup gating.

vpa.py detectors for top-5 volume-price action patterns, outputs p__vpa__* flags and optional conf__vpa__*.

registry.py feature pack composition.

qx-screener/

sip.py universe selection, deterministic top-N by rel volume.

qx-backtest/

policies/

vwap_revert.py rule policy (entry: close<vwap & rvol≥min; exit: vwap touch/timeout).

ml_vpa.py policy that consumes VPA features + model score threshold.

engine.py signals→orders→fills→positions→trades→equity; bps/per-share costs; slippage tick model; artifact writers.

metrics.py run metrics.

qx-risk/

atr_stop.py stop distance and sizing so qty * ATR * atr_mult ≤ max_risk_frac * equity; writes stop_dist_ps.

CLI & Experiments

qx_cli/exp/

entry_ab.py orchestrates A/B: load_bars→features→SIP→policy→risk→engine; writes manifest.json, real inputs_checksum.json.

cost_sweep.py, risk_grid.py, regime_slice.py sensitivity tools.

experiments/ configs

vwap_revert/strategy.yaml plus overlays for thresholds & SIP on/off.

ml_vpa/ dataset builder, model train manifest, inference config.

Artifacts (output only)

runs/<run_id>/
signals.parquet, orders.parquet, fills.parquet, positions.parquet, equity.parquet, trades.parquet, risk_rejects.parquet, allocation_log.parquet, metrics.json

experiments/<exp_id>/
manifest.json, inputs_checksum.json, compare.{json,md}

Reporting

qx-report/ readers that produce compare summaries from artifacts only.

LLM-accessible warehouse (optional but planned)

~/strategy_repo/ Parquet facts/dims, DuckDB warehouse.db, ingestors, views, MCP server.
