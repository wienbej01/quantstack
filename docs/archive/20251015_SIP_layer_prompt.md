
# 20251015_SIP_layer_prompt.md
**Mission:** Implement HMM_SIP filtering as a first-class **Universe Selector** in QuantStack, with strict determinism, artifact-first reporting, and A/B-comparable runs. Output must integrate cleanly with existing `qx-*` packages, require **no writes to the data lake**, and preserve the fairness tuple: `(bars_norm_hash, features_hash, sip_hash, config_hash, seed)`.

**Audience:** Claude Code operating in a local Linux workspace with shell and editor tools.

---

## Operating Envelope (read this first)
- **Repo root:** `~/quantstack`
- **Read-only lake:** `~/gcs-mount/gold` (canonical) and optional `~/gcs-mount/bronze` for pre/after-market. Never write to either.
- **Time handling:** Bar timestamps are **UTC ns**. Any ET calendar logic must be **derived** without mutating `ts`. All persisted artifacts remain UTC ns.
- **Determinism:** Stable dtype casts, frames sorted `[symbol, ts]`, fixed seeds. Any shortlist produced by HMM_SIP must be reproducible from config + inputs.
- **Fairness:** Extend `inputs_checksum.json` to include a deterministic `sip_hash` representing the **effective** SIP eligibility map used by the run.
- **Artifacts as truth:** Analysis reads from `runs/<run_id>/*.parquet` and `experiments/<exp_id>/*`. No backdoor reads from the lake during reporting.

---

## Deliverable Summary
1. **New selector:** `qx_screener.hmm_sip.HMMSIPUniverseSelector` implementing QuantStack’s UniverseSelector contract.
2. **Adapter:** lightweight reader that ingests precomputed HMM_SIP outputs from `~/hybrid-local` or computes a minimal **premarket** shortlist from Gold only for MVP fallback.
3. **Config + overlays:** YAMLs under `experiments/` to toggle `legacy_sip` vs `hmm_sip`, including thresholds and top-k. 
4. **Hashing:** Deterministic `sip_hash` integrated into `experiments/*/inputs_checksum.json` via `qx_core.hashers.hash_sip_map(..)`.
5. **Tests:** Pytest unit + integration covering ET-day derivation, shortlist determinism, hashing stability, and A/B wiring.
6. **Docs:** A concise READMEsnippet and CLI run recipes.
7. **No engine/policy changes** required for MVP. Policy will consume the new universe map transparently.

---

## High-level Design
HMM_SIP provides either:
- **External shortlist**: premarket Top-K per ET trading day from `~/hybrid-local/signals/sip/universe/pre/*.parquet` plus optional intraday minute scores. This is the most direct integration and fastest to stabilize.
- **Gold-only fallback**: when no external file exists, compute a cheap premarket score using Gold pre-open bars (gap, pre rVol) with fixed parameters. This guarantees the stack runs anywhere while you wire models later.

**Selector output contract:** `Dict[int_ts_ns, Set[str]]` mapping **every decision bar** to the eligible set. For MVP we broadcast the daily Top-K to all RTH bars of that ET day. In advanced phases we can tighten eligibility minutes using minute-level `p_hat` thresholds.

---

## Sprint Plan (for Claude Code)

### Sprint 0 — Preflight and contracts (0.5 day)
**Goal:** Confirm contracts and toolchain. No code mutation beyond scaffolding.
- [ ] Scan repo: `ls -la ~/quantstack` and `find qx-* -maxdepth 3`
- [ ] Confirm UniverseSelector entry points in `qx_screener/sip.py` and how `entry_ab.py` supplies `universe_map` to `policy.generate_signals`.
- [ ] Open `qx_core/schemas.py`, `contracts.py`, `hashers.py` and confirm available helpers.
- [ ] Create a feature branch `feat/hmm-sip-selector`.

**Exit checks:**
- [ ] Document exact `universe_map` type and where it is hashed. If no hasher exists for SIP, we will add `hash_sip_map` in `qx_core/hashers.py`.

---

### Sprint 1 — Minimal HMMSIP selector with external shortlist (1 day)
**Goal:** Produce a working selector consuming precomputed Top-K from `~/hybrid-local`. Deterministic, UTC-safe, and hashable.

**Tasks:**
- [ ] Create module: `qx-screener/src/qx_screener/hmm_sip.py` with:
  - `@dataclass HMMSIPConfig` including `top_k`, `min_dv_pre`, `score_floor`, `universe_file`, `external_premarket_root="~/hybrid-local/signals/sip/universe/pre"` and `enable_gold_fallback: bool`.
  - `class HMMSIPUniverseSelector(UniverseSelector)` with `select(df, ref, **params) -> Dict[int, Set[str]]`.
  - Loader `_load_external_premarket(target_et_date) -> DataFrame` reading parquet for the ET date, normalizing `symbol` to str upper, sorting deterministically.
  - Broadcast function `_broadcast_daily_shortlist_to_rth_ts(df_bars_utc, shortlist, calendar_et)` returning the per-`ts` set for **RTH bars only**.
  - Fallback `_compute_gold_premarket_shortlist(df_bars_utc) -> List[str]` with fixed scoring: `score = 0.6*z(pre_rvol) + 0.4*z(|gap_pct|)`; compute ET day via derived calendar; window = 04:00–09:29 ET.
- [ ] In `qx_core/hashers.py`, add `hash_sip_map(universe_map) -> str`:
  - Canonicalize as sequence of `(ts:int64, tuple(sorted(symbols)))` then serialize to bytes and blake2b digest with fixed salt; unit test against order-insensitive inputs.
- [ ] Wire `sip_hash` emission into `qx_cli/exp/entry_ab.py` so `inputs_checksum.json` includes it.

**Tests (pytest):**
- [ ] `tests/test_hmm_sip_selector_mvp.py`: given a small bars frame for an ET day and a synthetic external shortlist, ensure output eligibility map matches broadcasting rules, and `hash_sip_map` stable.
- [ ] `tests/test_hash_sip_map.py`: permutations of symbols and ts yield identical hash.

**Acceptance:**
- [ ] Run a smoke A/B using legacy vs HMM_SIP broadcasting identical top_k. `metrics.json` present, `inputs_checksum.json` includes stable `sip_hash`.
- [ ] No writes to lake.

**Sample commands:**
```bash
cd ~/quantstack
pytest -q tests/test_hmm_sip_selector_mvp.py
python -m qx_cli exp entry-ab   --cfg experiments/vwap_revert/strategy.yaml   --variants experiments/vwap_revert/overlays/policy_*.yaml   --name vwap_pilot_hmmsip_mvp
jq '.' experiments/*/inputs_checksum.json | head -n 40
```

---

### Sprint 2 — Config overlays and AB switch (0.5 day)
**Goal:** Make SIP implementation selectable via config with zero code changes to policies/engine.

**Tasks:**
- [ ] Add `experiments/_shared/sip/hmm_sip.yaml` with selector block and parameters.
- [ ] Add overlays:
  - `experiments/vwap_revert/overlays/sip_legacy.yaml` → keep current behavior.
  - `experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml` → turn on HMMSIP selector with `top_k: 40`.
- [ ] Extend `qx_cli/exp/entry_ab.py` to read a `sip.selector: {type: legacy|hmm_sip}` and instantiate appropriately.

**Tests:**
- [ ] Config roundtrip test: loading both overlays yields different `sip_hash` but identical `bars_norm_hash` and `features_hash`.

**Acceptance:**
- [ ] Two-entry A/B completes with distinct `sip_hash` values and valid artifacts under `runs/`.

---

### Sprint 3 — Gold-only robust fallback (1 day)
**Goal:** When `~/hybrid-local` files are absent, compute premarket shortlist entirely from Gold, still deterministic.

**Tasks:**
- [ ] Implement ET-calendar utilities in `qx_core/timecal.py`: derive ET date boundaries from UTC ns without mutating stored `ts` values.
- [ ] Implement premarket slice (04:00–09:29 ET), compute `gap_pct`, `pre_rvol` (vs RTH rolling baseline), z-score cross-sectionally for that day, rank and select `top_k` with ties resolved deterministically by `(score desc, symbol asc)`.
- [ ] Add strict input validators for required columns and dtypes.

**Tests:**
- [ ] Unit test on fixed small dataset with known premarket metrics and expected shortlist.
- [ ] Determinism test: stable shortlist with randomized row order, same `sip_hash`.

**Acceptance:**
- [ ] Running with `enable_gold_fallback: true` and no external files yields valid shortlist and full E2E artifacts.

---

### Sprint 4 — Performance and caching (0.5 day)
**Goal:** Make selection scale to 1000+ symbols without drama.

**Tasks:**
- [ ] Add simple in-process LRU for external parquet reads keyed by `(et_date, path, mtime)` with TTL hours.
- [ ] Vectorize premarket calculations; avoid per-symbol Python loops.

**Tests:**
- [ ] Benchmark test on synthetic 1000-symbol day; ensure selector < 30s on dev box.

**Acceptance:**
- [ ] Cache hit visual in logs, no correctness drift.

---

### Sprint 5 — Minute-level p̂ gate as optional feature (1.5 days)
**Goal:** If minute-level HMM probabilities are available under `~/hybrid-local/signals/sip/1m/<SYM>/<YYYY>/<YYYY-MM>.parquet`, tighten eligibility map intraday.

**Tasks:**
- [ ] Add optional `p_hat_threshold` and `min_minutes_in_state` to `HMMSIPConfig`.
- [ ] Ingest minute-level `p_hat` aligned on UTC `ts`; eligibility at minute `t` if `p_hat >= threshold` and symbol is in the day’s Top-K.
- [ ] Broadcast rule becomes: intersection of Top-K and minute-level gate, restricted to RTH bars.

**Tests:**
- [ ] Given synthetic `p_hat` series, confirm eligibility shrinks only when threshold is binding.
- [ ] Hash stability: `sip_hash` changes only when the eligibility map changes.

**Acceptance:**
- [ ] E2E run shows different `signals.parquet` counts vs MVP with a visible eligibility contraction/expansion, and expected `sip_hash` delta.

---

### Sprint 6 — QA, docs, and CLI recipes (0.5 day)
**Goal:** Polish and document.

**Tasks:**
- [ ] Write `qx-screener/README_hmm_sip.md` summarizing config keys and expected external file schemas.
- [ ] Add CLI snippets to `tools/README_smoke.md` for one-day and two-week pilots.
- [ ] Log line at start of run printing: selector type, top_k, thresholds, external roots, and computed `sip_hash` preview (first 8 chars).

**Acceptance:**
- [ ] Docs render; lints/tests clean; smoke command runs green.

---

## File and Code Skeletons (create these; fill TODOs as indicated)

### `qx-screener/src/qx_screener/hmm_sip.py` (skeleton)
```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Set, List, Optional
import pandas as pd

from qx_core.contracts import UniverseSelector
from qx_core.hashers import hash_sip_map
from qx_core.validators import validate_bars_dataframe

ET_TZ = "America/New_York"

@dataclass
class HMMSIPConfig:
    top_k: int = 40
    score_floor: float = 0.0
    universe_file: Optional[str] = None
    external_premarket_root: str = str(Path.home() / "hybrid-local" / "signals" / "sip" / "universe" / "pre")
    enable_gold_fallback: bool = True
    p_hat_threshold: Optional[float] = None
    min_minutes_in_state: int = 0

class HMMSIPUniverseSelector(UniverseSelector):
    name: str = "hmm_sip"

    def __init__(self, cfg: HMMSIPConfig):
        self.cfg = cfg

    def select(self, bars_utc: pd.DataFrame, ref: Dict, **params) -> Dict[int, Set[str]]:
        validate_bars_dataframe(bars_utc)
        target_et_date: str = ref.get("target_date")
        if not target_et_date:
            raise ValueError("target_date required for HMM_SIP selector")

        shortlist = self._load_external_premarket(target_et_date)
        if shortlist is None and self.cfg.enable_gold_fallback:
            shortlist = self._compute_gold_premarket_shortlist(bars_utc, target_et_date)

        if not shortlist:
            return {}

        universe_map = self._broadcast_daily_shortlist_to_rth_ts(bars_utc, shortlist, target_et_date)
        # this hash will be consumed upstream into inputs_checksum.json
        _ = hash_sip_map(universe_map)
        return universe_map

    def _load_external_premarket(self, target_et_date: str) -> Optional[List[str]]:
        # TODO: implement parquet read from self.cfg.external_premarket_root
        return None

    def _compute_gold_premarket_shortlist(self, bars_utc: pd.DataFrame, target_et_date: str) -> List[str]:
        # TODO: implement deterministic premarket metrics from gold-ONLY bars
        return []

    def _broadcast_daily_shortlist_to_rth_ts(self, bars_utc: pd.DataFrame, shortlist: List[str], target_et_date: str) -> Dict[int, Set[str]]:
        # TODO: restrict to RTH for the ET date and map every ts to the same set(shortlist)
        return {}
```

### `qx_core/hashers.py` (new helper)
```python
import hashlib
from typing import Dict, Set, Tuple, List

def hash_sip_map(universe_map: Dict[int, Set[str]]) -> str:
    items: List[Tuple[int, Tuple[str, ...]]] = []
    for ts, syms in universe_map.items():
        items.append((int(ts), tuple(sorted(map(str, syms)))))
    items.sort(key=lambda x: x[0])
    b = bytearray()
    for ts, syms in items:
        b.extend(ts.to_bytes(8, byteorder="little", signed=True))
        for s in syms:
            b.extend(s.encode("utf-8"))
            b.append(0x00)
        b.append(0xFF)
    return hashlib.blake2b(bytes(b), digest_size=16, person=b"qx_sip_v1").hexdigest()
```

---

## Config Overlays
Create:
- `experiments/_shared/sip/hmm_sip.yaml`
- `experiments/vwap_revert/overlays/sip_legacy.yaml`
- `experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml`

Example snippet:
```yaml
sip:
  selector:
    type: hmm_sip
    params:
      top_k: 40
      enable_gold_fallback: true
      p_hat_threshold: null
```

---

## Test Matrix
- **Unit:** hashing stability, ET calendar slice, shortlist ranking/ties, broadcast to RTH only.
- **Integration:** legacy vs hmmsip runs produce distinct `sip_hash` with identical bars/features hashes.
- **Performance:** 1000-symbol synthetic ET day under 30s wall time.
- **Determinism:** identical outputs across repeated runs; identical `sip_hash` across reorders.

---

## Run Recipes
```bash
# Unit tests
pytest -q tests/test_hash_sip_map.py
pytest -q tests/test_hmm_sip_selector_mvp.py

# One-day pilot A/B
python -m qx_cli exp entry-ab   --cfg experiments/vwap_revert/strategy.yaml   --variants experiments/vwap_revert/overlays/sip_legacy.yaml,experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml   --name vwap_hmmsip_ab_2024_01_03

# Two-week pilot
python -m qx_cli exp entry-ab   --cfg experiments/vwap_revert/strategy.yaml   --variants experiments/vwap_revert/overlays/sip_legacy.yaml,experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml   --name vwap_hmmsip_ab_2w
```

---

## Definition of Done (MVP)
- `HMMSIPUniverseSelector` produces a deterministic eligibility map driven by external premarket Top-K or Gold-only fallback.
- `inputs_checksum.json` includes a stable `sip_hash`.
- A/B runs complete with artifacts in `runs/` and show differing `sip_hash` while keeping `bars_norm_hash` and `features_hash` identical.
- No writes to lake; all timestamps remain UTC ns in persisted artifacts.

---

## Notes and Pitfalls
- **ET derivation:** never mutate `ts`. Derive ET day for slicing only; write nothing back.
- **Static broadcast vs minute gates:** MVP uses **static daily shortlist**. Minute-level p̂ is optional and lands in Sprint 5.
- **Ties:** Always resolve with a secondary key `symbol asc`. Write this into tests.
- **Costs/budgets:** If you see zero trades, check `risk_rejects.parquet` before blaming selector.
- **Fairness:** Changing `top_k` or threshold intentionally changes `sip_hash`. Keep `seed` fixed across A/B.

---

## Changelog
- 2025-10-15: Initial Claude Code implementation plan and scaffolds.
