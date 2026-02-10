# L2‑VWAP Investigation Report (Jan 30, 2026)

## Scope
Analyze:
1) `/home/jacobw/api-exported-logs.txt`
2) system audit logs
3) L2‑VWAP trade logic and code
4) L2 data in `~/quantstack/data` to evaluate VWAP/L2 criteria

**Goal:** Determine whether trades were taken but not captured, not taken due to market, or not taken due to logical/code/API issues.

---

## Final Determination
**Result: 3) No trades were taken due to logical/code/API problems.**

Evidence indicates the strategy generated valid signals and L2 criteria were met, but **every order submission failed** with an event‑loop error, preventing any trade from reaching IBKR or the database.

---

## 1) API Logs (`/home/jacobw/api-exported-logs.txt`)
- No occurrences of `VWAP`/`l2-vwap`/`l2_vwap` in API logs.
- Executions on Jan 30 are exclusively **L2SCALP** orderRefs (e.g., `L2_SCALPING_ORDERS_200_L2SCALP_*`).
- **No evidence that L2‑VWAP orders were submitted or filled at IBKR.**

**Conclusion:** No VWAP trades occurred at the broker level; missing DB writes are not the root cause.

---

## 2) System Audit Logs (`~/quantstack/logs/audit/audit_2026-01-30.*`)
- Only **SERVICE_START / SERVICE_STOP / SERVICE_ERROR** events for `l2-vwap-reversion`.
- **No `TRADE_SIGNAL` audit events** for l2‑vwap on Jan 30.
- Key ET timestamps from audit JSONL:
  - **09:20:34 ET**: service start (symbols `VZ, HL, FCX`)
  - **09:28:03 ET**: service start (same symbols)
  - **10:23–10:25 ET**: stop events
  - **10:32:25 ET**: IBKR connection failure

**Conclusion:** The audit layer shows no trade events because order submissions never succeeded.

---

## 3) L2‑VWAP Trade Logic & Code Bugs
### Strategy Logic (expected)
- **Entry (LONG):** `close <= VWAP * 0.995`
- **Entry (SHORT):** `close >= VWAP * 1.005`
- **L2 filter:**
  - Long: `depth_bid/depth_ask >= 1.165`
  - Short: `depth_bid/depth_ask <= 0.858`
- Orders submitted via bracket order API.

### Runtime Evidence (Jan 30 log)
From `/home/jacobw/quantstack/l2_vwap_reversion/logs/vwap_reversion_20260130.log`:
- **Strategy generated valid LONG signals** (e.g., FCX).
- **Every bracket order submission failed** with:
  - `Failed to submit bracket order for FCX: This event loop is already running`
- No “Bracket order:” success log lines.
- No “Position opened” / “Trade opened” lines.

**Conclusion:** Trades were **blocked by the order submission path**, specifically an event loop conflict in the IBKR async/sync calls.

---

## 4) L2 Data Check (`~/quantstack/data/l2/...`)
L2 files exist for **2026‑01‑30**:
- `symbol=FCX`, `symbol=HL`, `symbol=VZ`

Computed L2 ratio stats (depth_bid / depth_ask):
- **FCX**: `>= 1.165` in **82.89%** of rows
- **HL**: `>= 1.165` in **27.02%**, `<= 0.858` in **64.80%**
- **VZ**: `<= 0.858` in **83.96%**

**Conclusion:** L2 filter criteria were frequently met, so market/L2 conditions were not the limiting factor.

---

## Systemd / Service Layer Notes
From `journalctl --user -u l2-vwap-reversion.service`:
- Early failure: `Failed at step GROUP ... Operation not permitted`
- Multiple **IBKR connection refused** errors (`127.0.0.1:7494`)
- **ClientId already in use** errors later

These are reliability issues but **not the primary reason for zero trades**, since signals were generated and order submission failed during runtime.

---

## Final Answer Against Requested Options
1) **Trades taken but not captured by DB?**
   - **No.** No VWAP orders or executions in API logs; no audit TRADE_SIGNAL events.

2) **No trades due to market conditions?**
   - **No.** VWAP deviations and L2 ratios met thresholds, and signals were generated.

3) **No trades due to logical/code/API problems?**
   - **Yes.** Repeated `This event loop is already running` errors prevented order submission.

---

## Key Files Referenced
- `/home/jacobw/api-exported-logs.txt`
- `/home/jacobw/quantstack/logs/audit/audit_2026-01-30.*`
- `/home/jacobw/quantstack/l2_vwap_reversion/logs/vwap_reversion_20260130.log`
- `/home/jacobw/quantstack/l2_vwap_reversion/src/strategy.py`
- `/home/jacobw/quantstack/l2_vwap_reversion/src/execution/order_manager.py`
- `/home/jacobw/quantstack/l2_vwap_reversion/src/main.py`
- `/home/jacobw/quantstack/data/l2/l2_maximum/features/date=2026-01-30/*`
