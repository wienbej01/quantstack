# DATA CONTRACTS

## Bronze (source; **do not mutate**)
- Variant 1 (short): `t,o,h,l,c,v,vw?,n` (epoch ms in `t`)
- Variant 2 (long): `ts,open,high,low,close,volume,trades,session,date_et,...`
- Forex edge case: `timestamp:int64` without timezone
- Manual `ts` may exist in some files; treat as diagnostic only.

## Silver (normalized; **planned only**, deferred)
Canonical bar schema (UTC):
- `ts: timestamp[ns, tz=UTC]`
- `symbol: string`
- `open, high, low, close: float64`
- `volume: int64`
- `trades: int64?`
- Optional: `vwap, session, date_et`

Partitioning: `family/symbol=SYM/date=YYYY-MM-DD/part-*.parquet`

Normalization map (in‑memory only for hashing during runs):
`t→ts, o→open, h→high, l→low, c→close, v→volume, vw→vwap, n→trades` plus casting and tz→UTC.

## Gold (analysis‑ready; **additive only**)
Allowed:
- Derived scalars (turnover, spread), optional `vwap` if absent upstream
- Calendar/session labels, `_dq_flags`

Not allowed:
- Resampling across session boundaries
- Timestamp shifts or altering close semantics
- Signal engineering (belongs in features packages)
