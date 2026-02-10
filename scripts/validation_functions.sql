-- Database validation functions for trade recording integrity

-- Function to check for orphaned fills
CREATE OR REPLACE FUNCTION validate_fills_have_trades()
RETURNS TABLE(
    symbol TEXT,
    fill_count BIGINT,
    trade_count BIGINT,
    orphaned_fills BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        f.symbol,
        COUNT(*) as fill_count,
        COUNT(DISTINCT t.trade_id) as trade_count,
        COUNT(*) - COUNT(DISTINCT t.trade_id) * 2 as orphaned_fills
    FROM fills f
    LEFT JOIN trades t ON (
        f.order_id = t.entry_order_id OR 
        f.order_id = t.exit_order_id
    )
    WHERE f.timestamp::date >= CURRENT_DATE - INTERVAL '7 days'
    GROUP BY f.symbol
    HAVING COUNT(*) > COUNT(DISTINCT t.trade_id) * 2;
END;
$$ LANGUAGE plpgsql;

-- Function to check for zero-slippage exits
CREATE OR REPLACE FUNCTION validate_exit_prices()
RETURNS TABLE(
    trade_id TEXT,
    symbol TEXT,
    system TEXT,
    entry_price REAL,
    exit_price REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        t.trade_id::TEXT,
        t.symbol,
        t.system,
        t.entry_price,
        t.exit_price
    FROM trades t
    WHERE t.entry_time::date >= CURRENT_DATE - INTERVAL '7 days'
      AND t.status = 'CLOSED'
      AND t.entry_price = t.exit_price
      AND t.gross_pnl = 0;
END;
$$ LANGUAGE plpgsql;

-- Usage examples:
-- SELECT * FROM validate_fills_have_trades();
-- SELECT * FROM validate_exit_prices();
