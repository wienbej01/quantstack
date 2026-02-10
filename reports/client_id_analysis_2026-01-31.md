# IBKR Client ID Analysis & Management Plan

**Date:** 2026-01-31  
**Scope:** Analyze client ID usage across systemd services, determine if clashes caused l2-vwap failure, design management system

---

## 1. Root Cause Analysis: L2-VWAP Failure

### Primary Failure: Event Loop Conflict (NOT Client ID)

The analysis report (`l2_vwap_2026-01-30_analysis.md`) correctly identifies the **primary failure**:

```
Failed to submit bracket order for FCX: This event loop is already running
```

This is an **async/sync conflict** in the ib_insync library, NOT a client ID clash. The error occurs when:
- Code calls synchronous `ib.placeOrder()` from within an already-running asyncio event loop
- The l2-vwap strategy runs in a loop that's already async, then tries to call blocking IB methods

### Secondary Issues Observed

From journalctl logs mentioned in the report:
1. `Connection refused (127.0.0.1:7494)` - Gateway not running at startup
2. `ClientId already in use` - Client ID conflicts (later in session)

### Verdict: Client ID is a Contributing Factor, Not Root Cause

- **Root cause:** Event loop conflict in order submission code
- **Contributing factor:** Client ID clashes cause reconnection failures
- **Both need fixing** for reliable overnight operation

---

## 2. Current Client ID Allocation (Discovered)

| Service | Module | Client ID Range | Config Source |
|---------|--------|-----------------|---------------|
| l2-collector | qx-l2 | 1-99 | `maximum_l2.yaml: client_id: 1` |
| intraday-paper | intraday_stack | 100-199 | `paper_trading.yaml: client_id: 115` |
| l2-scalping | l2_scalping | 200-299 | `ibkr.yaml: order_client_id_base: 200, data_client_id_base: 250` |
| l2-vwap-reversion | l2_vwap_reversion | 300-399 | `ibkr.yaml: order_client_id: 300, data_client_id: 350` |
| ml-paper-trading | scripts/live_trading | ??? | Not configured (uses default) |
| ibkr-preflight | intraday_stack | 998 | Hardcoded |
| monitor_systems | intraday_stack | 99 | Hardcoded |

### Identified Problems

1. **l2-vwap uses FIXED IDs (300, 350)** - No increment on reconnect, causes "ClientId already in use"
2. **ml-paper-trading has NO configured client ID** - Uses library default, likely conflicts
3. **l2-collector uses ID 1** - Low ID, may conflict with manual testing
4. **No central registry** - Each service manages its own range independently
5. **Overlapping concerns** - Some services use 2 IDs (data + orders), others use 1

---

## 3. IBKR Gateway Client ID Behavior

### Key Facts

1. **Client IDs are cached by Gateway** for ~15 minutes after disconnect
2. **Same client ID cannot reconnect** until cache expires
3. **Max 32 concurrent connections** per Gateway instance
4. **Client ID range:** 0-999999 (but 0 is reserved)

### Why Clashes Happen

When a service crashes/restarts:
1. Gateway still holds the old client ID in cache
2. Service tries to reconnect with same ID
3. Gateway rejects: "ClientId already in use"
4. Service fails to start

### Solution: Increment on Reconnect

L2-scalping already implements this via `ClientIDManager`:
- Stores current ID in state file
- Increments within range on each connect
- Wraps back to base when max reached

---

## 4. Proposed Client ID Allocation Scheme

### Reserved Ranges (100 IDs each)

| Range | Service | Purpose |
|-------|---------|---------|
| 1-99 | l2-collector | L2 data collection (read-only) |
| 100-199 | intraday-paper | Intraday paper trading |
| 200-299 | l2-scalping | L2 scalping (orders: 200-249, data: 250-299) |
| 300-399 | l2-vwap-reversion | VWAP mean reversion (orders: 300-349, data: 350-399) |
| 400-499 | ml-paper-trading | ML-based paper trading |
| 500-599 | RESERVED | Future services |
| 900-999 | utilities | Preflight, monitoring, manual testing |

### Per-Service Sub-Allocation

For services needing separate order/data connections:
- **Orders:** base to base+49 (e.g., 200-249)
- **Data:** base+50 to base+99 (e.g., 250-299)

---

## 5. Client ID Management System Design

### Option A: Decentralized (Recommended)

Each service manages its own range using a shared `ClientIDManager` class:

```
cpapi/client_id_manager.py  (shared library)
├── get_next_id(service_name, id_type) -> int
├── release_id(service_name, id_type)
├── State stored in: ~/.quantstack/client_ids/{service}.json
└── Wraps within assigned range
```

**Pros:**
- No single point of failure
- Services can start independently
- Simple file-based state

**Cons:**
- No cross-service coordination
- Can't detect conflicts at runtime

### Option B: Centralized (Lock File)

Single lock file with all active client IDs:

```
~/.quantstack/client_ids/active.lock
├── JSON: {service: [id1, id2], ...}
├── File locking for concurrent access
└── Cleanup on service exit
```

**Pros:**
- Can detect conflicts
- Single source of truth

**Cons:**
- Lock contention
- Stale entries if service crashes

### Recommendation: Option A (Decentralized)

- Simpler, more robust
- Conflicts are rare with proper range allocation
- L2-scalping already uses this pattern successfully

---

## 6. Can We Kill Stale Client IDs?

### Answer: NO (Not via API)

IBKR Gateway does not expose an API to:
- List active client IDs
- Force-disconnect a client ID
- Clear the client ID cache

### Workarounds

1. **Restart Gateway** - Clears all cached IDs (disruptive)
2. **Wait 15 minutes** - Cache expires naturally
3. **Use different ID** - Increment within range (best solution)

---

## 7. Implementation Plan

### Phase 1: Fix L2-VWAP Event Loop (Critical) ✅ COMPLETED

Fixed async/sync conflict in `l2_vwap_reversion/src/execution/order_manager.py`:

```python
# Before (broken):
self.session.ib.qualifyContracts(contract)
parent_trade = self.session.ib.placeOrder(contract, parent)

# After (fixed):
self.session.call(self.session.ib.qualifyContracts, contract, timeout=10)
parent_trade = self.session.call(self.session.ib.placeOrder, contract, parent, timeout=10)
```

All `placeOrder()` and `qualifyContracts()` calls now use `session.call()` wrapper.

### Phase 2: Add Client ID Management to L2-VWAP ✅ COMPLETED

1. Created shared `cpapi/client_id_manager.py`:
   - `ClientIDManager` class with increment-on-reconnect
   - State persisted to `~/.quantstack/client_ids/{service}.json`
   - Wraps within assigned range

2. Updated `l2_vwap_reversion/config/ibkr.yaml`:
   ```yaml
   ibkr:
     order_client_id_base: 300
     data_client_id_base: 350
     client_id_max: 399
   ```

3. Updated `l2_vwap_reversion/src/main.py`:
   - Imports `ClientIDManager`
   - Creates manager from config
   - Gets dynamic IDs on startup

### Phase 3: Standardize All Services ✅ COMPLETED

1. Created central registry: `~/.quantstack/client_id_ranges.yaml`
2. L2-scalping already has `ClientIDManager` (no changes needed)
3. ml-paper-trading discontinued (skipped)

### Phase 4: Add Monitoring (Deferred)

- Client IDs now logged on connect via `ClientIDManager`
- Full audit integration deferred to audit logging TODO

---

## 8. Quick Reference: Client ID Config Locations

| Service | Config File | Keys |
|---------|-------------|------|
| l2-collector | `qx-l2/configs/maximum_l2.yaml` | `system.client_id` |
| intraday-paper | `intraday_stack/configs/paper_trading.yaml` | `system.client_id`, `ibkr.client_id_data`, `ibkr.client_id_exec` |
| l2-scalping | `l2_scalping/config/ibkr.yaml` | `order_client_id_base`, `data_client_id_base`, `client_id_max` |
| l2-vwap | `l2_vwap_reversion/config/ibkr.yaml` | `order_client_id`, `data_client_id` |

---

## 9. Summary

| Issue | Severity | Fix |
|-------|----------|-----|
| Event loop conflict in l2-vwap | **CRITICAL** | Use async placeOrder or session.call() wrapper |
| Fixed client IDs in l2-vwap | HIGH | Add ClientIDManager with increment-on-reconnect |
| No client ID for ml-paper | MEDIUM | Add config with range 400-499 |
| No central registry | LOW | Document ranges, add validation |

### Priority Order

1. **Fix event loop** (root cause of zero trades)
2. **Add client ID management to l2-vwap** (prevents reconnect failures)
3. **Standardize other services** (future-proofing)

---

## 10. Files Modified/Created

```
# Phase 1: Event loop fix ✅
l2_vwap_reversion/src/execution/order_manager.py  # Used session.call() for all IB calls

# Phase 2: Client ID management ✅
cpapi/client_id_manager.py                        # NEW: Shared manager class
l2_vwap_reversion/config/ibkr.yaml               # Added _base and _max keys
l2_vwap_reversion/src/main.py                    # Uses ClientIDManager

# Phase 3: Standardization ✅
~/.quantstack/client_id_ranges.yaml              # NEW: Central range registry
```

---

## 11. Testing Summary

### ClientIDManager Tests ✅
- Increment on get: PASS
- Wrap-around at max: PASS
- State persistence: PASS
- Config loading: PASS

### Syntax Validation ✅
- `order_manager.py`: PASS
- `client_id_manager.py`: PASS
- `main.py`: PASS

### Integration Test (Pending)
- Requires IBKR Gateway running
- Will validate on next trading session
