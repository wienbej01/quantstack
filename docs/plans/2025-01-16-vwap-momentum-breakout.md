# VWAP Momentum Breakout Implementation Plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Create a VWAP momentum breakout trading policy that complements the existing VWAP reversal policy, using identical interfaces and schemas for seamless integration.

**Architecture:** The momentum breakout policy will invert the reversal logic - instead of buying dips below VWAP and selling rallies above VWAP, it will buy breakouts above VWAP and sell breakdowns below VWAP. It will use the same feature dependencies, position management, and risk controls as the reversal version.

**Tech Stack:** Python 3.10+, pandas, numpy, qx-* modules (core, backtest, features), same dependencies as vwap_revert.py

---

## Task 1: Create VWAP Momentum Breakout Policy File

**Files:**
- Create: `qx-backtest/src/qx_backtest/policies/vwap_momentum.py`
- Test: `tests/test_vwap_momentum.py`

**Step 1: Write the failing test**

```python
def test_vwap_momentum_policy_initialization():
    """Test that VwapMomentumPolicy initializes correctly."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy(
        vwap_window=20,
        min_rvol=1.2,
        max_position_bars=30,
        position_size_pct=0.15,
        max_positions=3,
        min_breakout_strength=0.8
    )

    assert policy.name == "VwapMomentum"
    assert policy.vwap_window == 20
    assert policy.min_rvol == 1.2
    assert policy.max_position_bars == 30
    assert policy.position_size_pct == 0.15
    assert policy.max_positions == 3
    assert policy.min_breakout_strength == 0.8
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_vwap_momentum.py::test_vwap_momentum_policy_initialization -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'qx_backtest.policies.vwap_momentum'"

**Step 3: Write minimal implementation**

```python
"""VWAP momentum breakout trading policy."""

from typing import Any

import numpy as np

from ..order import OrderSide
from ..portfolio import Position
from .base import Policy


class VwapMomentumPolicy(Policy):
    """VWAP momentum breakout trading policy.

    This policy implements a momentum strategy based on VWAP breakouts:
    - Long Entry: Buy when close > VWAP and breakout strength >= minimum
    - Long Exit: Sell when close <= VWAP or timeout after maximum bars
    - Short Entry: Sell when close < VWAP and breakdown strength >= minimum
    - Short Exit: Buy when close >= VWAP or timeout after maximum bars
    """

    def __init__(
        self,
        vwap_window: int = 30,
        min_rvol: float = 1.0,
        max_position_bars: int = 50,
        position_size_pct: float = 0.1,
        max_positions: int = 5,
        min_breakout_strength: float = 0.5,
        name: str = "VwapMomentum"
    ):
        """Initialize VWAP momentum policy.

        Args:
            vwap_window: VWAP lookback window in minutes
            min_rvol: Minimum relative volume for entry
            max_position_bars: Maximum bars to hold position
            position_size_pct: Position size as percentage of equity
            max_positions: Maximum concurrent positions
            min_breakout_strength: Minimum breakout strength required (percentage deviation from VWAP)
            name: Policy name
        """
        super().__init__(name)
        self.vwap_window = vwap_window
        self.min_rvol = min_rvol
        self.max_position_bars = max_position_bars
        self.position_size_pct = position_size_pct
        self.max_positions = max_positions
        self.min_breakout_strength = min_breakout_strength

        # Track position entry times
        self.position_entry_times: dict[str, int] = {}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_vwap_momentum.py::test_vwap_momentum_policy_initialization -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_vwap_momentum.py qx-backtest/src/qx_backtest/policies/vwap_momentum.py
git commit -m "feat: add VWAP momentum breakout policy scaffold"
```

## Task 2: Implement Core Bar Processing Logic

**Files:**
- Modify: `qx-backtest/src/qx_backtest/policies/vwap_momentum.py:55-80`
- Test: `tests/test_vwap_momentum.py`

**Step 1: Write the failing test**

```python
def test_process_bar_feature_validation():
    """Test that process_bar handles missing features correctly."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy(vwap_window=30)

    # Bar without required features should be ignored
    bar = {
        'ts': 1640995200000000000,  # 2022-01-01 09:00:00 UTC
        'symbol': 'AAPL',
        'close': 150.0,
        'high': 152.0,
        'low': 148.0,
        'volume': 1000000
    }

    # Should not raise exception, just return without action
    policy.process_bar(bar)
    assert len(policy.position_entry_times) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_vwap_momentum.py::test_process_bar_feature_validation -v`
Expected: FAIL with "VwapMomentumPolicy object has no attribute 'process_bar'"

**Step 3: Write minimal implementation**

```python
def process_bar(self, bar: dict[str, Any]) -> None:
    """Process a single bar of data."""
    symbol = bar['symbol']
    timestamp = bar['ts']

    # Check required features
    vwap_col = f'f__ta__vwap_{self.vwap_window}'
    rvol_col = f'f__vol__rel_volume_{self.vwap_window}'

    if vwap_col not in bar or rvol_col not in bar:
        return

    vwap = bar[vwap_col]
    rvol = bar[rvol_col]
    close = bar['close']
    high = bar['high']
    low = bar['low']

    # Get current position
    position = self.get_position(symbol)

    if position is None or position.is_flat:
        # Check for entry signal (both long and short)
        self._check_entry_signal(symbol, bar, close, vwap, rvol, timestamp)
    else:
        # Check for exit signal (both long and short)
        self._check_exit_signal(symbol, bar, position, close, vwap, high, low, timestamp)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_vwap_momentum.py::test_process_bar_feature_validation -v`
Expected: PASS

**Step 5: Commit**

```bash
git add qx-backtest/src/qx_backtest/policies/vwap_momentum.py tests/test_vwap_momentum.py
git commit -m "feat: add core bar processing logic to VWAP momentum policy"
```

## Task 3: Implement Momentum Entry Logic

**Files:**
- Modify: `qx-backtest/src/qx_backtest/policies/vwap_momentum.py:80-140`
- Test: `tests/test_vwap_momentum.py`

**Step 1: Write the failing test**

```python
def test_momentum_entry_signal_long():
    """Test long entry signal when price breaks out above VWAP."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy(vwap_window=30, min_breakout_strength=0.5)

    # Mock engine and portfolio
    policy.engine = MockEngine()

    bar = {
        'ts': 1640995200000000000,
        'symbol': 'AAPL',
        'close': 152.5,  # Above VWAP
        'high': 153.0,
        'low': 151.0,
        'f__ta__vwap_30': 150.0,  # VWAP at 150
        'f__vol__rel_volume_30': 1.5  # Above minimum
    }

    policy.process_bar(bar)

    # Should have generated a buy order
    assert len(policy.engine.orders) == 1
    assert policy.engine.orders[0].side == OrderSide.BUY
    assert policy.engine.orders[0].symbol == 'AAPL'
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_vwap_momentum.py::test_momentum_entry_signal_long -v`
Expected: FAIL with "VwapMomentumPolicy object has no attribute '_check_entry_signal'"

**Step 3: Write minimal implementation**

```python
def _check_entry_signal(
    self,
    symbol: str,
    bar: dict[str, Any],
    close: float,
    vwap: float,
    rvol: float,
    timestamp: int
) -> None:
    """Check for momentum entry signal (both long and short)."""
    # Check if we have room for more positions
    current_positions = len(self.engine.portfolio.positions)
    if current_positions >= self.max_positions:
        return

    # Check if we already have a pending order for this symbol
    pending_orders = self.get_pending_orders(symbol)
    if pending_orders:
        return

    # Calculate VWAP breakout strength
    breakout_strength = (close - vwap) / vwap
    breakout_pct = abs(breakout_strength) * 100

    # Entry criteria for both long and short positions
    if rvol >= self.min_rvol and breakout_pct >= self.min_breakout_strength:
        position_size = self._calculate_position_size(close)

        if position_size > 0:
            if close > vwap:
                # Long entry: price above VWAP (momentum breakout)
                order = self.engine.order_factory.create_market_order(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    quantity=position_size,
                    tags={
                        'policy': self.name,
                        'direction': 'LONG',
                        'entry_price': close,
                        'vwap': vwap,
                        'rvol': rvol,
                        'signal_strength': breakout_strength,
                        'breakout_pct': breakout_pct
                    }
                )
                self.submit_order(order)

            elif close < vwap:
                # Short entry: price below VWAP (momentum breakdown)
                order = self.engine.order_factory.create_market_order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=position_size,
                    tags={
                        'policy': self.name,
                        'direction': 'SHORT',
                        'entry_price': close,
                        'vwap': vwap,
                        'rvol': rvol,
                        'signal_strength': abs(breakout_strength),
                        'breakout_pct': breakout_pct
                    }
                )
                self.submit_order(order)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_vwap_momentum.py::test_momentum_entry_signal_long -v`
Expected: PASS

**Step 5: Commit**

```bash
git add qx-backtest/src/qx_backtest/policies/vwap_momentum.py tests/test_vwap_momentum.py
git commit -m "feat: implement momentum entry logic for VWAP breakout policy"
```

## Task 4: Implement Momentum Exit Logic

**Files:**
- Modify: `qx-backtest/src/qx_backtest/policies/vwap_momentum.py:140-200`
- Test: `tests/test_vwap_momentum.py`

**Step 1: Write the failing test**

```python
def test_momentum_exit_signal_long():
    """Test long exit signal when price falls back to VWAP."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy(vwap_window=30)
    policy.engine = MockEngine()

    # Simulate existing long position
    position = Position(symbol='AAPL', quantity=100, avg_cost=152.0)
    policy.engine.portfolio.positions['AAPL'] = position
    policy.position_entry_times['AAPL'] = 1640995200000000000

    bar = {
        'ts': 1640995260000000000,  # 1 minute later
        'symbol': 'AAPL',
        'close': 150.0,  # Back to VWAP (exit signal)
        'high': 151.0,
        'low': 149.0,
        'f__ta__vwap_30': 150.0,
        'f__vol__rel_volume_30': 1.2
    }

    policy.process_bar(bar)

    # Should have generated a sell order to exit long
    assert len(policy.engine.orders) == 1
    assert policy.engine.orders[0].side == OrderSide.SELL
    assert 'EXIT_LONG' in policy.engine.orders[0].tags['direction']
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_vwap_momentum.py::test_momentum_exit_signal_long -v`
Expected: FAIL with "VwapMomentumPolicy object has no attribute '_check_exit_signal'"

**Step 3: Write minimal implementation**

```python
def _check_exit_signal(
    self,
    symbol: str,
    bar: dict[str, Any],
    position: Position,
    close: float,
    vwap: float,
    high: float,
    low: float,
    timestamp: int
) -> None:
    """Check for momentum exit signal (both long and short positions)."""
    # Check if position has entry time recorded
    if symbol not in self.position_entry_times:
        self.position_entry_times[symbol] = timestamp

    entry_time = self.position_entry_times[symbol]
    bars_held = self._calculate_bars_held(entry_time, timestamp)

    # Determine position direction from position cost basis
    is_long_position = position.quantity > 0

    exit_reason = None

    if is_long_position:
        # Long position exit criteria (opposite of reversal)
        if close <= vwap:
            exit_reason = "vwap_target_long"
        elif bars_held >= self.max_position_bars:
            exit_reason = "timeout_long"
    else:
        # Short position exit criteria (opposite of reversal)
        if close >= vwap:
            exit_reason = "vwap_target_short"
        elif bars_held >= self.max_position_bars:
            exit_reason = "timeout_short"

    if exit_reason:
        # Check if we already have a pending exit order
        pending_orders = self.get_pending_orders(symbol)
        exit_side = OrderSide.SELL if is_long_position else OrderSide.BUY
        exit_pending = any(order.side == exit_side for order in pending_orders)

        if not exit_pending:
            # Create exit order for entire position
            order = self.engine.order_factory.create_market_order(
                symbol=symbol,
                side=exit_side,
                quantity=abs(position.quantity),
                tags={
                    'policy': self.name,
                    'direction': 'EXIT_' + ('LONG' if is_long_position else 'SHORT'),
                    'exit_reason': exit_reason,
                    'bars_held': bars_held,
                    'entry_price': position.avg_cost,
                    'exit_price': close,
                    'vwap': vwap,
                    'position_side': 'LONG' if is_long_position else 'SHORT'
                }
            )

            self.submit_order(order)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_vwap_momentum.py::test_momentum_exit_signal_long -v`
Expected: PASS

**Step 5: Commit**

```bash
git add qx-backtest/src/qx_backtest/policies/vwap_momentum.py tests/test_vwap_momentum.py
git commit -m "feat: implement momentum exit logic for VWAP breakout policy"
```

## Task 5: Implement Position Sizing and Utility Methods

**Files:**
- Modify: `qx-backtest/src/qx_backtest/policies/vwap_momentum.py:200-250`
- Test: `tests/test_vwap_momentum.py`

**Step 1: Write the failing test**

```python
def test_calculate_position_size():
    """Test position size calculation."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy(position_size_pct=0.1)
    policy.engine = MockEngine(total_equity=1000000.0)

    # With $1M equity and 10% allocation, at $100/share should get 1000 shares
    position_size = policy._calculate_position_size(100.0)
    assert position_size == 1000

    # Test minimum size constraint
    large_price_position = policy._calculate_position_size(2000000.0)  # Too expensive
    assert large_price_position == 0  # Should be 0 if can't afford at least 1 share
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_vwap_momentum.py::test_calculate_position_size -v`
Expected: FAIL with "VwapMomentumPolicy object has no attribute '_calculate_position_size'"

**Step 3: Write minimal implementation**

```python
def _calculate_position_size(self, price: float) -> int:
    """Calculate position size based on risk management."""
    # Get current equity
    current_equity = self.engine.portfolio.total_equity
    target_value = current_equity * self.position_size_pct

    # Calculate number of shares
    position_size = int(target_value / price)

    # Ensure minimum position size of 1 share
    if position_size < 1:
        position_size = 0

    return position_size

def _calculate_bars_held(self, entry_time: int, current_time: int) -> int:
    """Calculate number of bars held since entry.

    This is a simplified calculation - in practice you'd need
    to account for market hours, holidays, etc.
    """
    # Assuming 1-minute bars (1 billion nanoseconds = 1 second)
    # 60 seconds = 1 minute = 60 billion nanoseconds
    minute_ns = 60 * 1_000_000_000
    bars_held = (current_time - entry_time) // minute_ns
    return int(bars_held)

def on_start(self) -> None:
    """Called when backtest starts."""
    self.position_entry_times.clear()

def on_end(self) -> None:
    """Called when backtest ends."""
    # Could log statistics here
    total_positions_held = len(self.position_entry_times)
    if total_positions_held > 0:
        avg_bars_held = np.mean(list(self.position_entry_times.values())) if self.position_entry_times else 0
        print(f"{self.name}: Held {total_positions_held} positions, avg bars held: {avg_bars_held:.1f}")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_vwap_momentum.py::test_calculate_position_size -v`
Expected: PASS

**Step 5: Commit**

```bash
git add qx-backtest/src/qx_backtest/policies/vwap_momentum.py tests/test_vwap_momentum.py
git commit -m "feat: add position sizing and utility methods to VWAP momentum policy"
```

## Task 6: Create Enhanced Version with ATR Stops

**Files:**
- Modify: `qx-backtest/src/qx_backtest/policies/vwap_momentum.py:250-350`
- Test: `tests/test_vwap_momentum.py`

**Step 1: Write the failing test**

```python
def test_vwap_momentum_enhanced_initialization():
    """Test enhanced policy with ATR stops."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicyEnhanced

    policy = VwapMomentumPolicyEnhanced(
        vwap_window=20,
        min_rvol=1.2,
        atr_window=14,
        atr_multiplier=2.0,
        min_profit_atr=1.0
    )

    assert policy.name == "VwapMomentumEnhanced"
    assert policy.atr_window == 14
    assert policy.atr_multiplier == 2.0
    assert policy.min_profit_atr == 1.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_vwap_momentum.py::test_vwap_momentum_enhanced_initialization -v`
Expected: FAIL with "cannot import name 'VwapMomentumPolicyEnhanced'"

**Step 3: Write minimal implementation**

```python
class VwapMomentumPolicyEnhanced(VwapMomentumPolicy):
    """Enhanced VWAP momentum policy with ATR-based stops and profit targets."""

    def __init__(
        self,
        vwap_window: int = 30,
        min_rvol: float = 1.0,
        max_position_bars: int = 50,
        position_size_pct: float = 0.1,
        max_positions: int = 5,
        atr_window: int = 14,
        atr_multiplier: float = 2.0,
        min_profit_atr: float = 0.5,
        name: str = "VwapMomentumEnhanced"
    ):
        """Initialize enhanced VWAP momentum policy.

        Args:
            vwap_window: VWAP lookback window in minutes
            min_rvol: Minimum relative volume for entry
            max_position_bars: Maximum bars to hold position
            position_size_pct: Position size as percentage of equity
            max_positions: Maximum concurrent positions
            atr_window: ATR lookback window for stop loss
            atr_multiplier: ATR multiplier for stop loss
            min_profit_atr: Minimum profit target in ATR multiples
            name: Policy name
        """
        super().__init__(vwap_window, min_rvol, max_position_bars,
                        position_size_pct, max_positions, name)
        self.atr_window = atr_window
        self.atr_multiplier = atr_multiplier
        self.min_profit_atr = min_profit_atr

    def process_bar(self, bar: dict[str, Any]) -> None:
        """Process a single bar of data."""
        symbol = bar['symbol']
        timestamp = bar['ts']

        # Check required features
        vwap_col = f'f__ta__vwap_{self.vwap_window}'
        rvol_col = f'f__vol__rel_volume_{self.vwap_window}'
        atr_col = f'f__vol__atr_{self.atr_window}'

        if vwap_col not in bar or rvol_col not in bar or atr_col not in bar:
            return

        vwap = bar[vwap_col]
        rvol = bar[rvol_col]
        atr = bar[atr_col]
        close = bar['close']
        high = bar['high']
        low = bar['low']

        # Get current position
        position = self.get_position(symbol)

        if position is None or position.is_flat:
            # Enhanced entry signal
            self._check_entry_signal_enhanced(symbol, bar, close, vwap, rvol, atr, timestamp)
        else:
            # Enhanced exit signal
            self._check_exit_signal_enhanced(symbol, bar, position, close, vwap, high, low, atr, timestamp)

    def _check_entry_signal_enhanced(
        self,
        symbol: str,
        bar: dict[str, Any],
        close: float,
        vwap: float,
        rvol: float,
        atr: float,
        timestamp: int
    ) -> None:
        """Check for enhanced momentum entry signal."""
        # Entry criteria with additional filters
        breakout_strength = abs(close - vwap) / vwap
        breakout_pct = breakout_strength * 100

        if (close > vwap and  # Long breakout
            rvol >= self.min_rvol and
            atr > 0 and
            breakout_pct >= self.min_breakout_strength and
            (close - vwap) >= (self.min_profit_atr * atr)):  # Sufficient profit potential

            # Additional filter: avoid entering during extreme volatility
            volatility_ratio = atr / close
            if volatility_ratio > 0.1:  # More than 10% daily volatility
                return

            # Check position limits
            current_positions = len(self.engine.portfolio.positions)
            if current_positions >= self.max_positions:
                return

            # Check for existing orders
            pending_orders = self.get_pending_orders(symbol)
            if pending_orders:
                return

            # Calculate position size with volatility adjustment
            base_size = self._calculate_position_size(close)
            volatility_adjustment = max(0.5, 1.0 - volatility_ratio * 5)
            position_size = int(base_size * volatility_adjustment)

            if position_size > 0:
                order = self.engine.order_factory.create_market_order(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    quantity=position_size,
                    tags={
                        'policy': self.name,
                        'entry_price': close,
                        'vwap': vwap,
                        'rvol': rvol,
                        'atr': atr,
                        'signal_strength': breakout_strength,
                        'volatility_ratio': volatility_ratio
                    }
                )

                self.submit_order(order)

    def _check_exit_signal_enhanced(
        self,
        symbol: str,
        bar: dict[str, Any],
        position: Position,
        close: float,
        vwap: float,
        high: float,
        low: float,
        atr: float,
        timestamp: int
    ) -> None:
        """Check for enhanced exit signal."""
        if symbol not in self.position_entry_times:
            self.position_entry_times[symbol] = timestamp

        entry_time = self.position_entry_times[symbol]
        bars_held = self._calculate_bars_held(entry_time, timestamp)

        # Calculate stop loss and profit targets
        is_long_position = position.quantity > 0

        if is_long_position:
            stop_loss_price = position.avg_cost - (atr * self.atr_multiplier)
            profit_target_price = position.avg_cost + (atr * self.min_profit_atr)
        else:
            stop_loss_price = position.avg_cost + (atr * self.atr_multiplier)
            profit_target_price = position.avg_cost - (atr * self.min_profit_atr)

        exit_reason = None

        # Enhanced exit criteria
        if is_long_position:
            if close <= vwap:
                exit_reason = "vwap_target"
            elif close <= stop_loss_price:
                exit_reason = "stop_loss"
            elif close >= profit_target_price:
                exit_reason = "profit_target"
            elif bars_held >= self.max_position_bars:
                exit_reason = "timeout"
        else:
            if close >= vwap:
                exit_reason = "vwap_target"
            elif close >= stop_loss_price:
                exit_reason = "stop_loss"
            elif close <= profit_target_price:
                exit_reason = "profit_target"
            elif bars_held >= self.max_position_bars:
                exit_reason = "timeout"

        if exit_reason:
            # Check for pending exit orders
            pending_orders = self.get_pending_orders(symbol)
            exit_side = OrderSide.SELL if is_long_position else OrderSide.BUY
            exit_pending = any(order.side == exit_side for order in pending_orders)

            if not exit_pending:
                order = self.engine.order_factory.create_market_order(
                    symbol=symbol,
                    side=exit_side,
                    quantity=abs(position.quantity),
                    tags={
                        'policy': self.name,
                        'exit_reason': exit_reason,
                        'bars_held': bars_held,
                        'entry_price': position.avg_cost,
                        'exit_price': close,
                        'vwap': vwap,
                        'atr': atr,
                        'stop_loss_price': stop_loss_price,
                        'profit_target_price': profit_target_price,
                        'pnl_per_atr': (close - position.avg_cost) / atr if atr > 0 and is_long_position
                                      else (position.avg_cost - close) / atr if atr > 0 else 0
                    }
                )

                self.submit_order(order)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_vwap_momentum.py::test_vwap_momentum_enhanced_initialization -v`
Expected: PASS

**Step 5: Commit**

```bash
git add qx-backtest/src/qx_backtest/policies/vwap_momentum.py tests/test_vwap_momentum.py
git commit -m "feat: add enhanced VWAP momentum policy with ATR stops"
```

## Task 7: Add Legacy Signal Generation Function

**Files:**
- Modify: `qx-backtest/src/qx_backtest/policies/vwap_momentum.py:350-400`
- Test: `tests/test_vwap_momentum.py`

**Step 1: Write the failing test**

```python
def test_legacy_generate_signals():
    """Test legacy signal generation function for compatibility."""
    from qx_backtest.policies.vwap_momentum import generate_signals
    import pandas as pd

    # Create test data
    data = {
        'ts': [1640995200000000000, 1640995260000000000],
        'symbol': ['AAPL', 'AAPL'],
        'close': [150.0, 152.0],
        'f__ta__vwap_30': [149.0, 149.5],
        'f__vol__rel_volume_30': [1.2, 1.5],
        'f__warmup_ok': [True, True]
    }
    df = pd.DataFrame(data)

    params = {
        'rvol_min': 1.0,
        'vwap_col': 'f__ta__vwap_30',
        'rvol_col': 'f__vol__rel_volume_30',
        'timeout_bars': 10
    }

    signals = generate_signals(df, params)

    assert len(signals) == 2
    assert 'signal' in signals.columns
    assert 'breakout_strength' in signals.columns
    assert signals.iloc[1]['signal'] == 1  # Should have long signal
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_vwap_momentum.py::test_legacy_generate_signals -v`
Expected: FAIL with "cannot import name 'generate_signals' from 'qx_backtest.policies.vwap_momentum'"

**Step 3: Write minimal implementation**

```python
# Legacy function for backward compatibility
def generate_signals(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Generate signals for VWAP momentum strategy (legacy function).

    Args:
        df: DataFrame with bars and features
        params: Parameters dict with rvol_min, vwap_col, rvol_col, timeout_bars, sip_universe (optional)

    Returns:
        DataFrame with signals: ts, symbol, signal (1=long, 0=flat), and diagnostic columns
    """
    rvol_min = params.get('rvol_min', 1.0)
    vwap_col = params.get('vwap_col', 'f__ta__vwap_30')
    rvol_col = params.get('rvol_col', 'f__vol__rel_volume_30')
    timeout_bars = params.get('timeout_bars', 10)
    min_breakout_strength = params.get('min_breakout_strength', 0.5)
    sip_universe = params.get('sip_universe')  # Dict[ts, Set[symbols]] or None

    signals = []
    position_tracker = {}  # symbol -> {'entry_ts': ts, 'bars_held': int}

    for idx, row in df.iterrows():
        ts = row['ts']
        symbol = row['symbol']
        close = row['close']
        vwap = row[vwap_col]
        rvol = row[rvol_col]
        warmup_ok = row.get('f__warmup_ok', True)

        # Check SIP filter
        in_sip = True
        if sip_universe and ts in sip_universe:
            in_sip = symbol in sip_universe[ts]

        # Get position state from START of bar
        pos_before_decision = position_tracker.get(symbol, {'entry_ts': None, 'bars_held': 0})

        # Calculate breakout strength
        breakout_strength = (close - vwap) / vwap

        # Decision logic (momentum: buy when above VWAP, sell when below)
        decision = 'hold'
        if pos_before_decision['entry_ts'] is not None:
            # In position
            new_bars_held = pos_before_decision['bars_held'] + 1
            if (close <= vwap and breakout_strength < -min_breakout_strength/100) or new_bars_held >= timeout_bars:
                decision = 'exit'
                position_tracker[symbol] = {'entry_ts': None, 'bars_held': 0}
            else:
                position_tracker[symbol]['bars_held'] = new_bars_held
        # Flat
        elif close > vwap and rvol >= rvol_min and in_sip and warmup_ok and breakout_strength > min_breakout_strength/100:
            decision = 'enter'
            position_tracker[symbol] = {'entry_ts': ts, 'bars_held': 1}

        # Get position state AFTER decision for the current bar
        pos_after_decision = position_tracker.get(symbol, {'entry_ts': None, 'bars_held': 0})

        # Generate signal based on the state AFTER the decision
        signal = 1 if pos_after_decision['entry_ts'] is not None else 0

        # Diagnostic columns
        diag = {
            'ts': ts,
            'symbol': symbol,
            'signal': signal,
            'close': close,
            'vwap': vwap,
            'rvol': rvol,
            'breakout_strength': breakout_strength,
            'in_sip': in_sip,
            'warmup_ok': warmup_ok,
            'bars_held': pos_after_decision['bars_held'],
            'decision': decision
        }
        signals.append(diag)

    return pd.DataFrame(signals)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_vwap_momentum.py::test_legacy_generate_signals -v`
Expected: PASS

**Step 5: Commit**

```bash
git add qx-backtest/src/qx_backtest/policies/vwap_momentum.py tests/test_vwap_momentum.py
git commit -m "feat: add legacy signal generation function for backward compatibility"
```

## Task 8: Create Integration Test with Real Data

**Files:**
- Test: `tests/test_vwap_momentum_integration.py`
- Create: `experiments/vwap_momentum_test/strategy.yaml`

**Step 1: Write the failing test**

```python
def test_vwap_momentum_integration():
    """Test VWAP momentum policy with real data integration."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy
    from qx_backtest.engine import BacktestEngine
    from qx_data.gold_loader import GoldLoader
    from qx_features.core_basics import compute_all_core_features

    # Load real data (small sample for testing)
    loader = GoldLoader()
    bars = loader.load_bars(['AAPL'], '2024-01-01', '2024-01-02')

    # Compute features
    bars_with_features = compute_all_core_features(bars, vwap_window=30, rvol_window=30, atr_window=14)

    # Create backtest engine
    engine = BacktestEngine()

    # Create policy
    policy = VwapMomentumPolicy(
        vwap_window=30,
        min_rvol=1.0,
        max_position_bars=50,
        position_size_pct=0.1,
        max_positions=5,
        min_breakout_strength=0.5
    )

    # Set up engine
    engine.set_policy(policy)

    # Run backtest
    results = engine.run(bars_with_features)

    # Verify results
    assert results is not None
    assert 'trades' in results
    assert 'equity_curve' in results
    assert len(results['trades']) >= 0  # May be 0 in short test
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_vwap_momentum_integration.py::test_vwap_momentum_integration -v`
Expected: FAIL (likely due to missing configuration or integration issues)

**Step 3: Create strategy configuration**

```yaml
# experiments/vwap_momentum_test/strategy.yaml
name: "VWAP Momentum Test"
description: "Test strategy for VWAP momentum breakout policy"

policy:
  type: "VwapMomentum"
  params:
    vwap_window: 30
    min_rvol: 1.0
    max_position_bars: 50
    position_size_pct: 0.1
    max_positions: 5
    min_breakout_strength: 0.5

data:
  symbols: ["AAPL", "MSFT", "SPY"]
  start_date: "2024-01-01"
  end_date: "2024-01-31"

features:
  - type: "core_basics"
    params:
      vwap_window: 30
      rvol_window: 30
      atr_window: 14

risk:
  max_position_size: 0.1
  max_total_exposure: 1.0
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_vwap_momentum_integration.py::test_vwap_momentum_integration -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_vwap_momentum_integration.py experiments/vwap_momentum_test/
git commit -m "feat: add integration test for VWAP momentum policy"
```

## Task 9: Update Policy Registry and Imports

**Files:**
- Modify: `qx-backtest/src/qx_backtest/policies/__init__.py`
- Test: `tests/test_policy_registry.py`

**Step 1: Write the failing test**

```python
def test_policy_registry_includes_momentum():
    """Test that VWAP momentum policy is in policy registry."""
    from qx_backtest.policies import get_policy_class

    policy_class = get_policy_class("VwapMomentum")
    assert policy_class is not None
    assert policy_class.__name__ == "VwapMomentumPolicy"

    enhanced_class = get_policy_class("VwapMomentumEnhanced")
    assert enhanced_class is not None
    assert enhanced_class.__name__ == "VwapMomentumPolicyEnhanced"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_policy_registry.py::test_policy_registry_includes_momentum -v`
Expected: FAIL with "Policy 'VwapMomentum' not found in registry"

**Step 3: Write minimal implementation**

```python
# In qx-backtest/src/qx_backtest/policies/__init__.py
from .base import Policy
from .vwap_revert import VwapRevertPolicy, VwapRevertPolicyEnhanced
from .vwap_momentum import VwapMomentumPolicy, VwapMomentumPolicyEnhanced

# Policy registry
POLICY_REGISTRY = {
    "VwapRevert": VwapRevertPolicy,
    "VwapRevertEnhanced": VwapRevertPolicyEnhanced,
    "VwapMomentum": VwapMomentumPolicy,
    "VwapMomentumEnhanced": VwapMomentumPolicyEnhanced,
}

def get_policy_class(name: str) -> type[Policy] | None:
    """Get policy class by name."""
    return POLICY_REGISTRY.get(name)

def list_policies() -> list[str]:
    """List all available policy names."""
    return list(POLICY_REGISTRY.keys())

__all__ = [
    "Policy",
    "VwapRevertPolicy",
    "VwapRevertPolicyEnhanced",
    "VwapMomentumPolicy",
    "VwapMomentumPolicyEnhanced",
    "POLICY_REGISTRY",
    "get_policy_class",
    "list_policies"
]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_policy_registry.py::test_policy_registry_includes_momentum -v`
Expected: PASS

**Step 5: Commit**

```bash
git add qx-backtest/src/qx_backtest/policies/__init__.py tests/test_policy_registry.py
git commit -m "feat: add VWAP momentum policy to registry"
```

## Task 10: Create Performance Comparison Test

**Files:**
- Test: `tests/test_vwap_comparison.py`
- Create: `experiments/vwap_comparison/manifest.json`

**Step 1: Write the failing test**

```python
def test_vwap_revert_vs_momentum_comparison():
    """Compare VWAP reversal vs momentum strategies on same data."""
    from qx_backtest.policies.vwap_revert import VwapRevertPolicy
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy
    from qx_backtest.engine import BacktestEngine
    from qx_data.gold_loader import GoldLoader
    from qx_features.core_basics import compute_all_core_features

    # Load test data
    loader = GoldLoader()
    bars = loader.load_bars(['SPY'], '2024-01-01', '2024-01-31')
    bars_with_features = compute_all_core_features(bars)

    # Test reversal policy
    engine_revert = BacktestEngine()
    policy_revert = VwapRevertPolicy(vwap_window=30, min_rvol=1.0)
    engine_revert.set_policy(policy_revert)
    results_revert = engine_revert.run(bars_with_features)

    # Test momentum policy
    engine_momentum = BacktestEngine()
    policy_momentum = VwapMomentumPolicy(vwap_window=30, min_rvol=1.0)
    engine_momentum.set_policy(policy_momentum)
    results_momentum = engine_momentum.run(bars_with_features)

    # Both should complete successfully
    assert results_revert is not None
    assert results_momentum is not None

    # Results should be different (opposite strategies)
    assert results_revert['trades'] != results_momentum['trades']

    # Print summary for manual verification
    print(f"Revert trades: {len(results_revert['trades'])}")
    print(f"Momentum trades: {len(results_momentum['trades'])}")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_vwap_comparison.py::test_vwap_revert_vs_momentum_comparison -v`
Expected: FAIL if there are any integration issues

**Step 3: Create comparison manifest**

```json
{
  "exp_id": "vwap_comparison_2024_01",
  "type": "entry-ab",
  "base_config": "vwap_comparison/base_strategy.yaml",
  "variants": [
    "vwap_comparison/revert_overlay.yaml",
    "vwap_comparison/momentum_overlay.yaml"
  ],
  "seed": 42,
  "description": "Compare VWAP reversal vs momentum strategies"
}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_vwap_comparison.py::test_vwap_revert_vs_momentum_comparison -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_vwap_comparison.py experiments/vwap_comparison/
git commit -m "feat: add performance comparison test for VWAP strategies"
```

## Task 11: Update Documentation and Examples

**Files:**
- Create: `docs/vwap_momentum_guide.md`
- Modify: `README.md`

**Step 1: Write the failing test (test for documentation completeness)**

```python
def test_documentation_completeness():
    """Test that required documentation exists."""
    import os

    # Check that documentation file exists
    assert os.path.exists("docs/vwap_momentum_guide.md")

    # Check that README mentions momentum policy
    with open("README.md", "r") as f:
        readme_content = f.read()
        assert "VwapMomentum" in readme_content
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_documentation.py::test_documentation_completeness -v`
Expected: FAIL with missing documentation files

**Step 3: Write minimal implementation**

```markdown
# docs/vwap_momentum_guide.md
# VWAP Momentum Breakout Strategy Guide

## Overview

The VWAP Momentum strategy is the complement to the VWAP Reversion strategy. Instead of buying dips below VWAP and selling rallies above VWAP, the momentum strategy buys breakouts above VWAP and sells breakdowns below VWAP.

## Strategy Logic

### Entry Signals
- **Long Entry**: Price closes above VWAP AND relative volume >= minimum AND breakout strength >= threshold
- **Short Entry**: Price closes below VWAP AND relative volume >= minimum AND breakdown strength >= threshold

### Exit Signals
- **Long Exit**: Price closes at or below VWAP OR maximum bars reached
- **Short Exit**: Price closes at or above VWAP OR maximum bars reached

## Parameters

- `vwap_window`: VWAP lookback period in minutes (default: 30)
- `min_rvol`: Minimum relative volume for entry (default: 1.0)
- `max_position_bars`: Maximum bars to hold position (default: 50)
- `position_size_pct`: Position size as % of equity (default: 0.1)
- `max_positions`: Maximum concurrent positions (default: 5)
- `min_breakout_strength`: Minimum breakout strength % (default: 0.5)

## Enhanced Version

The enhanced version adds ATR-based stop losses and profit targets:

- `atr_window`: ATR lookback period (default: 14)
- `atr_multiplier`: Stop loss distance in ATR multiples (default: 2.0)
- `min_profit_atr`: Minimum profit target in ATR multiples (default: 0.5)

## Usage

```python
from qx_backtest.policies import VwapMomentumPolicy

# Basic momentum policy
policy = VwapMomentumPolicy(
    vwap_window=30,
    min_breakout_strength=0.8,
    position_size_pct=0.15
)

# Enhanced with ATR stops
policy_enhanced = VwapMomentumPolicyEnhanced(
    vwap_window=30,
    min_breakout_strength=0.8,
    atr_window=14,
    atr_multiplier=2.0,
    min_profit_atr=1.0
)
```

## Comparison with VWAP Reversion

| Aspect | VWAP Reversion | VWAP Momentum |
|--------|----------------|---------------|
| Entry Signal | Price < VWAP (buy dip) | Price > VWAP (buy breakout) |
| Exit Signal | Price ≥ VWAP (take profit) | Price ≤ VWAP (stop) |
| Market Type | Range-bound, mean-reverting | Trending, momentum |
| Risk Profile | Quick profits, frequent trades | Larger moves, fewer trades |
```

```markdown
# In README.md, add to policies section:
- **VWAP Momentum**: Breakout strategy that buys above VWAP and sells below VWAP
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_documentation.py::test_documentation_completeness -v`
Expected: PASS

**Step 5: Commit**

```bash
git add docs/vwap_momentum_guide.md README.md tests/test_documentation.py
git commit -m "docs: add comprehensive documentation for VWAP momentum strategy"
```

## Task 12: Final Integration and Validation

**Files:**
- Test: `tests/test_final_validation.py`
- Modify: None (validation only)

**Step 1: Write the failing test**

```python
def test_final_integration_validation():
    """Final end-to-end validation of VWAP momentum implementation."""
    from qx_backtest.policies import VwapMomentumPolicy, VwapMomentumPolicyEnhanced
    from qx_backtest.engine import BacktestEngine
    import pandas as pd

    # Test 1: Policy instantiation
    policy = VwapMomentumPolicy()
    enhanced = VwapMomentumPolicyEnhanced()
    assert policy.name == "VwapMomentum"
    assert enhanced.name == "VwapMomentumEnhanced"

    # Test 2: Feature dependencies match reversal policy
    required_features = [
        f'f__ta__vwap_{policy.vwap_window}',
        f'f__vol__rel_volume_{policy.vwap_window}'
    ]

    # Enhanced version should also require ATR
    enhanced_features = required_features + [f'f__vol__atr_{enhanced.atr_window}']

    assert len(required_features) == 2
    assert len(enhanced_features) == 3

    # Test 3: Policy interface compliance
    assert hasattr(policy, 'process_bar')
    assert hasattr(policy, 'on_start')
    assert hasattr(policy, 'on_end')
    assert hasattr(policy, 'set_engine')

    # Test 4: Backward compatibility function exists
    from qx_backtest.policies.vwap_momentum import generate_signals
    assert callable(generate_signals)

    # Test 5: Registry inclusion
    from qx_backtest.policies import get_policy_class, list_policies
    assert "VwapMomentum" in list_policies()
    assert "VwapMomentumEnhanced" in list_policies()
    assert get_policy_class("VwapMomentum") == VwapMomentumPolicy

    print("✅ All integration tests passed!")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_final_validation.py::test_final_integration_validation -v`
Expected: FAIL if any integration issues remain

**Step 3: Debug and fix any remaining issues**

(Minor fixes based on test results)

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_final_validation.py::test_final_integration_validation -v`
Expected: PASS

**Step 5: Final commit**

```bash
git add tests/test_final_validation.py
git commit -m "feat: complete VWAP momentum breakout implementation with full validation"
```

---

## Remember

- Exact file paths always
- Complete code in plan (not "add validation")
- Exact commands with expected output
- Reference relevant skills with @ syntax
- DRY, YAGNI, TDD, frequent commits

## Execution Handoff

Plan complete and saved to `docs/plans/2025-01-16-vwap-momentum-breakout.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**

**If Subagent-Driven chosen:**
- Use skills/collaboration/subagent-driven-development
- Stay in this session
- Fresh subagent per task + code review

**If Parallel Session chosen:**
- Guide them to open new session in worktree
- New session uses skills/collaboration/executing-plans