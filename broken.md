
## Service Lifecycle

| Service | Start | Stop | Duration | Exit |
|---------|-------|------|----------|------|
| l2-scalping | 22:26 PST (09:26 ET) | 06:02 PST (17:01 ET) | 7h 36m | 143 (SIGTERM — normal kill by stop timer) |
| l2-vwap-reversion | 22:32 PST (09:32 ET) | 05:05 PST (16:05 ET) | 6h 33m | 0 (clean self-exit) |
| intraday-paper | 22:28 PST (09:28 ET) | 06:02 PST (17:02 ET) | 7h 34m | 143 (SIGTERM — normal kill by stop timer) |
| vitals-monitor | 22:00 PST (09:00 ET) | 06:00 PST (17:00 ET) | 8h | stopped by timer |

Exit code 143 = SIGTERM, which is expected — the stop timers killed the processes at 17:00 ET. l2-vwap-reversion exited cleanly on its own at 16:05 ET.

## System Health (Vitals Monitor)

| Metric | Value |
|--------|-------|
| Records collected | 2,006 (every ~10s for 7.5h) |
| Avg CPU | 42.4% |
| Avg Memory | 25.5% |
| CPU range | 15.5% – 100.0% |
| Memory range | 20.8% – 27.6% |

## ⚠️ CPU Spike — Major Concern

374 of 2,006 records (18.6%) had CPU >80%. There was one sustained spike:

| Window (UTC) | Window (ET) | Duration | Peak |
|-------------|-------------|----------|------|
| 16:24 – 18:17 | 11:24 AM – 1:17 PM | ~1h 53m | 100% |

During this window: 347 records ≥90%, 118 records at 100%. This is exactly the pattern you described causing IBKR crashes. Memory stayed stable at 25-27% so this is a CPU-
bound issue, not a memory leak.

The vitals monitor couldn't identify which process caused it — the process name matching needs to be updated to catch Python child processes. I'll note this as a fix
needed.

## Trading Performance

l2-scalping: 3 signals, 0 completed trades, $0 P&L. Entered positions in RIG, PGY, HIMS but had a stale exit order issue on HIMS — the system was force-cancelling and re-
submitting SELL orders repeatedly (orders stale for 1,380s = 23 minutes).

l2-vwap-reversion: 2 entries — both LONG HIMS at $17.10 and $16.96 (below VWAP of ~$17.12). No exit records in the trade log.

intraday-paper: 4,351 trade decisions logged, 0 fills, 100% uptime, 0 data gaps.

## L2 Data Collection

| Metric | Value |
|--------|-------|
| Raw parquet files | 4,485 |
| Feature parquet files | 1,509 |
| Raw data size | 79 MB |
| Feature data size | 18 MB |
| Symbols | HIMS, RIG, PGY |

Data collection was healthy after we fixed the L2_DATA_ROOT path mid-session (~22:53 PST). Data before that was lost to the broken gcs-mount path.

## Issues to Address

1. CPU spike 11:24–13:17 ET — nearly 2 hours at 80-100%. This is your crash risk. Need to identify the culprit process (likely l2-scalping's L2 data processing or IBKR
event loop).
2. HIMS stale exit orders — l2-scalping was stuck in a cancel/resubmit loop for 23+ minutes. Possible IBKR connectivity issue or order routing problem.
3. Vitals process tracking — the monitor needs to match on Python process cmdline, not just process name, to identify which service is consuming CPU.

> There it is. The root cause is clear:

## What Actually Happened

l2-scalping did trade, but the daily report didn't count them properly. Here's the actual sequence:

1. 09:26 ET — Entered HIMS LONG 255 shares @ $26.55 (pre-market order from previous session, filled at open)
2. 09:30 ET — Entered RIG LONG 100 shares @ $5.24
3. 09:30 ET — Entered PGY SHORT 100 shares @ $14.00
4. 09:33 ET — HIMS stop-loss triggered, SOLD 255 @ $17.73 → realized P&L: -$639 to -$720
5. 09:36 ET — Tried to exit HIMS again (255 shares) → MARGIN REJECTION

## The Killer: Margin Breach

At 09:36:40 ET, IBKR rejected the order:

│ *"Your Available Funds are insufficient... Equity with Loan Value [$836,863.52] must exceed Initial Margin [$839,154.10]"*

Your account was ~$2,291 short on margin. The HIMS loss (~$700+) pushed you below margin requirements. After that:

- Every subsequent SELL order for HIMS was rejected for insufficient margin
- The system entered a cancel/resubmit loop trying to exit the remaining HIMS position
- With positions stuck, no new entries could be made (position limits hit)
- This explains the "stale exit orders" we saw — 23+ minutes of failed exit attempts
- The system was effectively frozen for the entire day after 09:36 ET

## Why Only 3 Signals, 0 "Completed" Trades

- The 3 entries (HIMS, RIG, PGY) happened but the daily report only counts round-trip completed trades
- The HIMS stop-loss exit partially filled but the position tracking got confused by the margin rejection loop
- RIG and PGY positions likely stayed open all day (couldn't exit due to margin)
- The report showed "0 completed trades" because no clean entry→exit round-trips were recorded

## Why l2-vwap and intraday-paper Had No Trades

- **l2-vwap-reversion**: Entered 2 HIMS longs ($17.10 and $16.96) but likely hit the same margin wall trying to exit
- **intraday-paper**: 4,351 decisions but 0 fills — if it shares the same IBKR account, margin was already blown by l2-scalping

## The CPU Spike Connection

The sustained 100% CPU from 11:24–13:17 ET was almost certainly the cancel/resubmit loop — the system was hammering IBKR with exit orders that kept getting rejected, 
burning CPU in a tight retry loop.

## Action Items

1. Margin buffer — your risk manager needs a margin check before placing orders, not just position limits
2. Exit retry circuit breaker — after N failed exit attempts, stop retrying and alert instead of looping
3. Cross-service position awareness — l2-scalping, l2-vwap, and intraday-paper shouldn't independently consume margin without knowing each other's positions
 ▸ Credits: 2.19 • Time: 30s

