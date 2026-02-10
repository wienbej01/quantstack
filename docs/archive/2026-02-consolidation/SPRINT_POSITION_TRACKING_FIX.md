# Sprint: Position Tracking & Trade Recording Fix

**Created**: 2026-01-29
**Priority**: CRITICAL
**Estimated Duration**: 2-3 days

## Problem Statement

The l2-scalping system executed 3,271 fills on Jan 28 but only recorded 4 trades in the database. The root cause is that the system:
1. Fires market orders without proper position lifecycle tracking
2. Does not link entry orders to exit orders (TP/SL)
3. Does not record partial fills correctly
4. Cannot distinguish between opening a new position vs adding to/closing existing positions

## Requirements

### Must Have
1. **Order Recording**: Every order placed must be recorded with intent (ENTRY, TP, SL, EXIT)
2. **Fill Recording**: Every fill must be recorded with link to parent order
3. **Position Lifecycle**: Entry and exit must be linked as a single trade record
4. **TP/SL Calculation**: Calculate TP/SL levels based on actual fill price, not signal price
5. **IB Integration**: Receive and process fill callbacks, partial fills, order status updates
6. **Trade Closure**: Record exit reason (TP hit, SL hit, system exit, EOD flatten)

### Database Schema

```sql
-- Orders table (already exists, needs enhancement)
ALTER TABLE orders ADD COLUMN IF NOT EXISTS intent TEXT;  -- ENTRY, TP, SL, FLATTEN, EXIT
ALTER TABLE orders ADD COLUMN IF NOT EXISTS parent_order_id INTEGER;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS trade_id TEXT;

-- Fills table (already exists, needs enhancement)  
ALTER TABLE fills ADD COLUMN IF NOT EXISTS trade_id TEXT;
ALTER TABLE fills ADD COLUMN IF NOT EXISTS is_partial BOOLEAN DEFAULT FALSE;

-- Trades table enhancement
ALTER TABLE trades ADD COLUMN IF NOT EXISTS tp_price REAL;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS sl_price REAL;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS tp_order_id INTEGER;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS sl_order_id INTEGER;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_order_id INTEGER;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_order_id INTEGER;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS partial_fills INTEGER DEFAULT 0;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS avg_entry_price REAL;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS avg_exit_price REAL;
```

## Architecture

```
Signal Generated
       │
       ▼
┌─────────────────┐
│ PositionManager │ ◄── Single source of truth for positions
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│  OrderTracker   │────►│   TradeJournal  │
└────────┬────────┘     └─────────────────┘
         │                      │
         ▼                      ▼
┌─────────────────┐     ┌─────────────────┐
│   IB Gateway    │     │   PostgreSQL    │
└────────┬────────┘     └─────────────────┘
         │
         ▼
    Fill Callbacks
         │
         ▼
┌─────────────────┐
│ FillProcessor   │ ◄── Updates PositionManager, calculates TP/SL
└─────────────────┘
```

## Sprint Tasks

### Phase 1: Core Infrastructure (Day 1)

#### Task 1.1: Create PositionManager class
**File**: `l2_scalping/src/position_manager.py`

**Key Design**: Each entry order creates a SEPARATE managed position with its own trade_id and TP/SL. Multiple concurrent entries for the same symbol are tracked independently.

```python
@dataclass
class ManagedPosition:
    trade_id: str
    symbol: str
    direction: str  # long/short
    target_qty: int
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    entry_order_id: int = 0
    tp_order_id: int = 0
    sl_order_id: int = 0
    tp_price: float = 0.0
    sl_price: float = 0.0
    status: str = "PENDING"  # PENDING, OPEN, CLOSING, CLOSED
    tp_sl_placed: bool = False
    last_tp_sl_update: float = 0.0  # timestamp of last TP/SL modification
    entry_fills: list = field(default_factory=list)
    exit_fills: list = field(default_factory=list)

class PositionManager:
    """Manages positions by ENTRY ORDER, not by symbol.
    
    Each entry order gets its own trade_id and independent TP/SL management.
    Multiple concurrent entries for same symbol are tracked separately.
    """
    
    TP_SL_UPDATE_BUFFER_SECONDS = 2.0  # Min time between TP/SL adjustments
    
    def __init__(self):
        # Key: entry_order_id -> ManagedPosition
        self.positions: dict[int, ManagedPosition] = {}
        # Index: symbol -> list of entry_order_ids (for lookup)
        self.symbol_index: dict[str, list[int]] = defaultdict(list)
    
    def create_position(self, entry_order_id: int, trade_id: str, 
                        symbol: str, direction: str, target_qty: int) -> ManagedPosition:
        """Create new position tied to specific entry order."""
        pos = ManagedPosition(
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            target_qty=target_qty,
            entry_order_id=entry_order_id,
        )
        self.positions[entry_order_id] = pos
        self.symbol_index[symbol].append(entry_order_id)
        return pos
    
    def get_position_by_order(self, order_id: int) -> ManagedPosition | None:
        """Get position by entry order ID."""
        return self.positions.get(order_id)
    
    def get_positions_for_symbol(self, symbol: str) -> list[ManagedPosition]:
        """Get all positions (including pending) for a symbol."""
        return [self.positions[oid] for oid in self.symbol_index.get(symbol, [])
                if oid in self.positions]
    
    def has_open_position(self, symbol: str) -> bool:
        """Check if any OPEN position exists for symbol."""
        return any(p.status == "OPEN" for p in self.get_positions_for_symbol(symbol))
    
    def count_pending_entries(self, symbol: str) -> int:
        """Count pending entry orders for symbol."""
        return sum(1 for p in self.get_positions_for_symbol(symbol) 
                   if p.status == "PENDING")
```

**Example: Concurrent Orders with TP/SL Adjustment**
```
Time 0.0s: Order 1 placed (100 shares) → Position A created (trade_id=AAA)
Time 0.5s: Order 1 fill 50 @ $50.00 → Position A: TP/SL placed for 50 shares, avg=$50.00
Time 1.0s: Order 2 placed (25 shares) → Position B created (trade_id=BBB)
Time 1.5s: Order 1 fill 50 @ $50.10 → Position A: filled=100, buffer not elapsed (1.0s < 2.0s)
Time 2.5s: Buffer elapsed → Position A: Adjust TP/SL to 100 shares @ avg=$50.05
Time 3.0s: Order 2 fill 25 @ $51.00 → Position B: TP/SL placed for 25 shares @ $51.00

Result: Two independent positions with separate TP/SL orders
- Position A: 100 shares @ avg $50.05, TP/SL adjusted to full qty
- Position B: 25 shares @ $51.00, independent TP/SL
```

#### Task 1.2: Create OrderTracker class
**File**: `l2_scalping/src/order_tracker.py`

```python
@dataclass  
class TrackedOrder:
    order_id: int
    trade_id: str
    symbol: str
    intent: str  # ENTRY, TP, SL, FLATTEN
    side: str
    quantity: int
    order_type: str  # MKT, LMT, STP
    limit_price: float = 0.0
    stop_price: float = 0.0
    status: str = "PENDING"
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    parent_order_id: int = 0
```

Responsibilities:
- Track all orders by order_id
- Link orders to trade_id
- Record order intent (ENTRY vs TP vs SL)
- Update status from IB callbacks

#### Task 1.3: Create FillProcessor class
**File**: `l2_scalping/src/fill_processor.py`

Responsibilities:
- Process IB fill callbacks
- Update OrderTracker with fill info
- Update PositionManager with fill info
- Trigger TP/SL order placement when entry is filled
- Trigger trade closure when exit is filled

### Phase 2: IB Integration (Day 1-2)

#### Task 2.1: Implement fill callback handler
**File**: `l2_scalping/src/main.py` (modify)

```python
def _on_fill(self, trade: Trade, fill: Fill):
    """Process fill from IB."""
    order_id = trade.order.orderId
    
    # Get tracked order
    tracked = self.order_tracker.get_order(order_id)
    if not tracked:
        logger.warning(f"Fill for untracked order {order_id}")
        return
    
    # Record fill
    self.fill_processor.process_fill(
        order_id=order_id,
        trade_id=tracked.trade_id,
        symbol=tracked.symbol,
        side=fill.execution.side,
        qty=fill.execution.shares,
        price=fill.execution.price,
        is_partial=(fill.execution.cumQty < tracked.quantity)
    )
```

#### Task 2.2: Implement order status callback handler

```python
def _on_order_status(self, trade: Trade):
    """Process order status update from IB."""
    order_id = trade.order.orderId
    status = trade.orderStatus.status
    
    self.order_tracker.update_status(order_id, status)
    
    if status == "Filled":
        self._handle_order_filled(trade)
    elif status == "Cancelled":
        self._handle_order_cancelled(trade)
```

#### Task 2.3: Implement TP/SL order placement and adjustment

**Key Design**: 
- TP/SL placed on FIRST fill (partial or full)
- TP/SL ADJUSTED on subsequent fills with time buffer (2 seconds)
- Each entry order has its own independent TP/SL orders

```python
class FillProcessor:
    TP_SL_UPDATE_BUFFER = 2.0  # seconds between TP/SL adjustments
    
    def process_entry_fill(self, position: ManagedPosition, fill: Fill):
        """Process fill for entry order, manage TP/SL."""
        # Update position
        old_qty = position.filled_qty
        position.filled_qty += int(fill.execution.shares)
        position.avg_fill_price = self._calc_weighted_avg(
            position.avg_fill_price, old_qty,
            fill.execution.price, int(fill.execution.shares)
        )
        position.entry_fills.append(fill)
        
        now = time.time()
        
        if not position.tp_sl_placed:
            # First fill - place TP/SL
            self._place_tp_sl(position)
            position.tp_sl_placed = True
            position.last_tp_sl_update = now
            position.status = "OPEN"
        elif now - position.last_tp_sl_update >= self.TP_SL_UPDATE_BUFFER:
            # Subsequent fill with buffer elapsed - adjust TP/SL
            self._adjust_tp_sl(position)
            position.last_tp_sl_update = now
    
    def _place_tp_sl(self, position: ManagedPosition):
        """Place initial TP/SL orders for position."""
        tp_price, sl_price, exit_side = self._calc_tp_sl_prices(position)
        
        # Create OCA group unique to this position
        oca_group = f"OCA_{position.trade_id[:8]}"
        
        # Place TP (limit order)
        tp_order = LimitOrder(exit_side, position.filled_qty, tp_price)
        tp_order.ocaGroup = oca_group
        tp_order.ocaType = 1
        tp_trade = self.ib.placeOrder(self.contracts[position.symbol], tp_order)
        
        # Place SL (stop order)
        sl_order = StopOrder(exit_side, position.filled_qty, sl_price)
        sl_order.ocaGroup = oca_group
        sl_order.ocaType = 1
        sl_trade = self.ib.placeOrder(self.contracts[position.symbol], sl_order)
        
        # Update position
        position.tp_order_id = tp_trade.order.orderId
        position.sl_order_id = sl_trade.order.orderId
        position.tp_price = tp_price
        position.sl_price = sl_price
        
        # Track orders
        self.order_tracker.add_order(position.tp_order_id, position.trade_id, "TP")
        self.order_tracker.add_order(position.sl_order_id, position.trade_id, "SL")
        
        logger.info(f"TP/SL placed for {position.symbol} trade={position.trade_id[:8]}: "
                    f"qty={position.filled_qty}, TP={tp_price}, SL={sl_price}")
    
    def _adjust_tp_sl(self, position: ManagedPosition):
        """Adjust existing TP/SL orders for new avg price and qty."""
        new_tp, new_sl, exit_side = self._calc_tp_sl_prices(position)
        
        # Cancel existing orders
        self.ib.cancelOrder(self._get_order(position.tp_order_id))
        self.ib.cancelOrder(self._get_order(position.sl_order_id))
        
        # Place new orders with updated qty and prices
        oca_group = f"OCA_{position.trade_id[:8]}"
        
        tp_order = LimitOrder(exit_side, position.filled_qty, new_tp)
        tp_order.ocaGroup = oca_group
        tp_order.ocaType = 1
        tp_trade = self.ib.placeOrder(self.contracts[position.symbol], tp_order)
        
        sl_order = StopOrder(exit_side, position.filled_qty, new_sl)
        sl_order.ocaGroup = oca_group
        sl_order.ocaType = 1
        sl_trade = self.ib.placeOrder(self.contracts[position.symbol], sl_order)
        
        # Update position
        old_tp_id, old_sl_id = position.tp_order_id, position.sl_order_id
        position.tp_order_id = tp_trade.order.orderId
        position.sl_order_id = sl_trade.order.orderId
        position.tp_price = new_tp
        position.sl_price = new_sl
        
        # Update tracker
        self.order_tracker.update_order_id(old_tp_id, position.tp_order_id)
        self.order_tracker.update_order_id(old_sl_id, position.sl_order_id)
        
        logger.info(f"TP/SL adjusted for {position.symbol} trade={position.trade_id[:8]}: "
                    f"qty={position.filled_qty}, TP={new_tp}, SL={new_sl}")
    
    def _calc_tp_sl_prices(self, position: ManagedPosition) -> tuple[float, float, str]:
        """Calculate TP/SL prices from current avg fill price."""
        if position.direction == "long":
            tp = round_to_tick(position.avg_fill_price * (1 + self.tp_pct))
            sl = round_to_tick(position.avg_fill_price * (1 - self.sl_pct))
            side = "SELL"
        else:
            tp = round_to_tick(position.avg_fill_price * (1 - self.tp_pct))
            sl = round_to_tick(position.avg_fill_price * (1 + self.sl_pct))
            side = "BUY"
        return tp, sl, side
    
    def _calc_weighted_avg(self, old_avg: float, old_qty: int, 
                           new_price: float, new_qty: int) -> float:
        """Calculate weighted average price."""
        if old_qty == 0:
            return new_price
        total_qty = old_qty + new_qty
        return (old_avg * old_qty + new_price * new_qty) / total_qty
```

**Fill Sequence Example (with adjustment)**:
```
Time 0.0: Entry order 1 placed (100 shares)
Time 0.5: Fill 50 @ $50.00 → TP/SL placed for 50 shares, avg=$50.00
Time 1.0: Fill 30 @ $50.10 → Buffer not elapsed (1.0 < 2.0), skip adjust
Time 3.0: Fill 20 @ $50.05 → Buffer elapsed, adjust TP/SL:
          - New avg = (50*50 + 30*50.10 + 20*50.05) / 100 = $50.04
          - Cancel old TP/SL, place new for 100 shares @ new avg
```

### Phase 3: Database Recording (Day 2)

#### Task 3.1: Enhance TradeJournal for full lifecycle

```python
def open_trade(self, trade_id: str, symbol: str, direction: str, 
               entry_order_id: int, target_qty: int, signal_price: float) -> None:
    """Record trade opening - called when entry order is placed."""
    
def record_entry_fill(self, trade_id: str, fill_price: float, fill_qty: int,
                      is_partial: bool) -> None:
    """Record entry fill - updates avg_entry_price."""
    
def record_tp_sl_orders(self, trade_id: str, tp_order_id: int, sl_order_id: int,
                        tp_price: float, sl_price: float) -> None:
    """Record TP/SL orders after entry is filled."""

def record_exit_fill(self, trade_id: str, fill_price: float, fill_qty: int,
                     exit_reason: str, is_partial: bool) -> None:
    """Record exit fill - updates avg_exit_price."""

def close_trade(self, trade_id: str, exit_reason: str, 
                avg_exit_price: float, pnl: float) -> None:
    """Record trade closure - called when position is fully closed."""
```

#### Task 3.2: Implement order recording

```python
def record_order(self, order_id: int, trade_id: str, symbol: str,
                 intent: str, side: str, qty: int, order_type: str,
                 limit_price: float = None, stop_price: float = None,
                 parent_order_id: int = None) -> None:
    """Record order placement."""
```

#### Task 3.3: Implement fill recording

```python
def record_fill(self, order_id: int, trade_id: str, symbol: str,
                side: str, qty: int, price: float, 
                is_partial: bool, exec_id: str) -> None:
    """Record fill execution."""
```

### Phase 4: Signal-to-Trade Flow (Day 2-3)

#### Task 4.1: Refactor signal handling

Current flow (broken):
```
Signal → Place Order → (fills happen) → Maybe record trade
```

New flow:
```
Signal → Check PositionManager → If no position:
    1. Generate trade_id
    2. Record trade opening (status=PENDING)
    3. Place entry order
    4. Track order with trade_id
    5. On fill callback:
       a. Record fill
       b. Update position avg price
       c. If fully filled:
          - Update trade status=OPEN
          - Calculate TP/SL from fill price
          - Place TP/SL orders
          - Record TP/SL orders
    6. On TP/SL fill:
       a. Record exit fill
       b. Cancel other order (OCA)
       c. Close trade with exit_reason
```

#### Task 4.2: Implement position check before signal

```python
def _can_open_position(self, symbol: str) -> bool:
    """Check if we can open a new position."""
    # Already have position?
    if self.position_manager.has_position(symbol):
        return False
    # Already have pending entry?
    if self.position_manager.has_pending_entry(symbol):
        return False
    return True
```

#### Task 4.3: Implement OCA (One-Cancels-All) for TP/SL

```python
def _place_oca_exit_orders(self, position: ManagedPosition):
    """Place TP and SL as OCA group."""
    oca_group = f"OCA_{position.symbol}_{position.trade_id[:8]}"
    
    tp_order = LimitOrder(...)
    tp_order.ocaGroup = oca_group
    tp_order.ocaType = 1  # Cancel other on fill
    
    sl_order = StopOrder(...)
    sl_order.ocaGroup = oca_group
    sl_order.ocaType = 1
```

### Phase 5: Testing & Validation (Day 3)

#### Task 5.1: Unit tests for PositionManager
- Test partial fill handling
- Test avg price calculation
- Test position state transitions

#### Task 5.2: Unit tests for OrderTracker
- Test order lifecycle
- Test order-trade linking

#### Task 5.3: Integration test with mock IB
- Test full signal-to-close flow
- Test partial fills
- Test TP hit scenario
- Test SL hit scenario
- Test system exit scenario

#### Task 5.4: Database verification
- Verify trades table has linked entry/exit
- Verify orders table has correct intent
- Verify fills table links to trades

## Migration Plan

1. **Backup**: Export current trades table
2. **Schema**: Run ALTER TABLE statements
3. **Deploy**: Deploy new code with feature flag disabled
4. **Test**: Run in paper mode for one session
5. **Enable**: Enable for live trading

## Success Criteria

1. Every order placed is recorded with intent
2. Every fill is recorded with trade_id link
3. Trades table shows entry_order_id and exit_order_id
4. Trades table shows tp_price and sl_price
5. Exit reason correctly identifies TP/SL/SYSTEM/EOD
6. P&L calculated from actual fill prices
7. No orphan orders or fills

## Files to Create/Modify

### New Files
- `l2_scalping/src/position_manager.py`
- `l2_scalping/src/order_tracker.py`
- `l2_scalping/src/fill_processor.py`
- `l2_scalping/tests/test_position_manager.py`
- `l2_scalping/tests/test_order_tracker.py`

### Modified Files
- `l2_scalping/src/main.py` - Integrate new components
- `l2_scalping/src/reporting/trade_journal.py` - Enhanced recording
- `intraday_stack/src/journal/event_store.py` - Schema updates

## Rollback Plan

If issues occur:
1. Disable l2-scalping service
2. Revert to previous main.py
3. Trades recorded during test period remain in DB (no data loss)
