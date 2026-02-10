#!/usr/bin/env python3
"""Monitor L2 Scalping Position Tracking System"""

import sys
import time
from pathlib import Path

# Add l2_scalping src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "l2_scalping" / "src"))

def check_position_tracking():
    """Check if position tracking components are working"""
    try:
        # Add l2_scalping src to path
        l2_path = str(Path(__file__).parent.parent / "l2_scalping" / "src")
        if l2_path not in sys.path:
            sys.path.insert(0, l2_path)
        
        import position_manager
        import order_tracker
        
        # Quick validation
        pm = position_manager.PositionManager()
        ot = order_tracker.OrderTracker()
        
        print(f"✅ Position tracking components loaded successfully")
        print(f"   - PositionManager: {len(pm)} positions")
        print(f"   - OrderTracker: {len(ot)} orders")
        return True
        
    except Exception as e:
        print(f"❌ Position tracking check failed: {e}")
        return False

def check_database_schema():
    """Check if database schema is updated"""
    try:
        # Add intraday_stack to path
        intraday_path = str(Path(__file__).parent.parent.parent / "intraday_stack" / "src")
        if intraday_path not in sys.path:
            sys.path.append(intraday_path)
        
        from journal.event_store import EventStore
        
        event_store = EventStore()
        if hasattr(event_store, 'conn') and event_store.conn:
            cursor = event_store.conn.cursor()
            
            # Check for new columns (PostgreSQL syntax)
            try:
                cursor.execute("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'orders' AND column_name = 'trade_id'
                """)
                
                if cursor.fetchone():
                    print("✅ Database schema updated (PostgreSQL)")
                    return True
            except:
                # Try SQLite syntax
                cursor.execute("PRAGMA table_info(orders)")
                columns = [row[1] for row in cursor.fetchall()]
                if 'trade_id' in columns:
                    print("✅ Database schema updated (SQLite)")
                    return True
            
            print("⚠️  Database schema not updated")
            return False
        else:
            print("⚠️  No database connection")
            return False
            
    except Exception as e:
        print(f"⚠️  Database schema check failed: {e}")
        return False

def main():
    print("🔍 L2 Scalping Position Tracking Monitor")
    print("=" * 50)
    
    all_good = True
    
    if not check_position_tracking():
        all_good = False
    
    if not check_database_schema():
        all_good = False
    
    if all_good:
        print("\n✅ All position tracking components are healthy")
        return 0
    else:
        print("\n❌ Some position tracking components have issues")
        return 1

if __name__ == "__main__":
    sys.exit(main())
