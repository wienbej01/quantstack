#!/usr/bin/env python3
"""
Startup Validation: Verify IOC Price Improvement is Configured
This runs BEFORE the trading system starts to ensure the fix is active.
"""

import sys
import yaml
from pathlib import Path

def validate_ioc_improvement():
    """Validate that entry order configuration is properly set"""
    
    config_dir = Path("/home/jacobw/quantstack/l2_scalping/config")
    
    try:
        # Load IBKR config
        with open(config_dir / "ibkr.yaml") as f:
            ibkr_config = yaml.safe_load(f)
        
        # Extract values
        entry_order_type = ibkr_config["orders"].get("entry_order_type", "LMT")
        improvement_ticks = ibkr_config["orders"].get("ioc_price_improvement_ticks", 0)
        tick_size = ibkr_config["orders"].get("tick_size", 0.01)
        
        # Calculate improvement for IOC orders
        use_ioc = entry_order_type == "IOC"
        price_improvement = improvement_ticks * tick_size if use_ioc else 0.0
        
        print("Entry Order Configuration Validation")
        print("=" * 50)
        print(f"entry_order_type: {entry_order_type}")
        print(f"improvement_ticks: {improvement_ticks}")
        print(f"tick_size: {tick_size}")
        print(f"price_improvement: ${price_improvement:.4f}")
        print()
        
        # Validate IOC-specific settings
        if use_ioc:
            if improvement_ticks == 0:
                print("❌ CRITICAL: ioc_price_improvement_ticks is 0")
                print("   No price improvement will be applied")
                print("   Orders will be placed at exact ask/bid")
                print("   This will result in ZERO FILLS")
                return False
            
            if price_improvement < 0.01:
                print(f"⚠️  WARNING: price_improvement is only ${price_improvement:.4f}")
                print("   This may not be enough for consistent fills")
                return False
            
            print("✅ IOC Price Improvement is PROPERLY CONFIGURED")
            print(f"   Orders will be improved by ${price_improvement:.4f}")
            print(f"   BUY orders: ask + ${price_improvement:.4f}")
            print(f"   SELL orders: bid - ${price_improvement:.4f}")
        else:
            print(f"✅ Entry order type: {entry_order_type}")
            if entry_order_type == "MKT":
                print("   Market orders will be used for entries")
            elif entry_order_type == "LMT":
                print("   Limit orders will be used for entries")
        
        return True
        
    except Exception as e:
        print(f"❌ ERROR: Failed to validate config: {e}")
        return False

if __name__ == "__main__":
    if validate_ioc_improvement():
        sys.exit(0)
    else:
        print()
        print("STARTUP BLOCKED: Fix configuration before trading")
        sys.exit(1)
