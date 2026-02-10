-- Trade Database v2 Schema
-- Source of truth: executions table (immutable)
-- Denormalized: trades_v2 table (computed from executions)

-- ============================================================================
-- EXECUTIONS TABLE (Source of Truth)
-- ============================================================================
CREATE TABLE IF NOT EXISTS executions (
    exec_id         VARCHAR(50) PRIMARY KEY,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ibkr_time       TIMESTAMPTZ NOT NULL,
    symbol          VARCHAR(10) NOT NULL,
    system          VARCHAR(20) NOT NULL,
    side            VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity        INTEGER NOT NULL,
    price           DECIMAL(12,4) NOT NULL,
    commission      DECIMAL(10,4) DEFAULT 0,
    exchange        VARCHAR(20),
    ibkr_order_id   INTEGER,
    ibkr_perm_id    INTEGER,
    trade_id        UUID,
    source          VARCHAR(20) NOT NULL CHECK (source IN ('CALLBACK', 'POLL', 'RECONCILE')),
    raw_data        JSONB
);

CREATE INDEX IF NOT EXISTS idx_exec_time ON executions(ibkr_time);
CREATE INDEX IF NOT EXISTS idx_exec_symbol ON executions(symbol);
CREATE INDEX IF NOT EXISTS idx_exec_trade ON executions(trade_id);
CREATE INDEX IF NOT EXISTS idx_exec_received ON executions(received_at);

-- ============================================================================
-- TRADE ORDER LINKS (Order -> Trade mapping)
-- ============================================================================
CREATE TABLE IF NOT EXISTS trade_order_links (
    trade_id        UUID NOT NULL,
    ibkr_order_id   INTEGER NOT NULL,
    system          VARCHAR(20),
    is_entry        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (trade_id, ibkr_order_id)
);

CREATE INDEX IF NOT EXISTS idx_trade_order_links_order ON trade_order_links(ibkr_order_id);
CREATE INDEX IF NOT EXISTS idx_trade_order_links_system ON trade_order_links(system);

-- ============================================================================
-- TRADES TABLE (Denormalized)
-- ============================================================================
CREATE TABLE IF NOT EXISTS trades_v2 (
    trade_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol              VARCHAR(10) NOT NULL,
    system              VARCHAR(20) NOT NULL,
    strategy            VARCHAR(50),
    substrategy         VARCHAR(50),
    direction           VARCHAR(5) NOT NULL CHECK (direction IN ('long', 'short')),
    signal_time         TIMESTAMPTZ,
    signal_price        DECIMAL(12,4),
    signal_strength     DECIMAL(8,4),
    signal_edge_bps     DECIMAL(8,2),
    signal_data         JSONB,
    entry_time          TIMESTAMPTZ,
    entry_price         DECIMAL(12,4),
    entry_qty           INTEGER,
    entry_slippage_bps  DECIMAL(8,2),
    entry_fills         JSONB DEFAULT '[]',
    entry_fill_count    INTEGER DEFAULT 0,
    exit_time           TIMESTAMPTZ,
    exit_price          DECIMAL(12,4),
    exit_qty            INTEGER,
    exit_slippage_bps   DECIMAL(8,2),
    exit_fills          JSONB DEFAULT '[]',
    exit_fill_count     INTEGER DEFAULT 0,
    exit_reason         VARCHAR(20),
    initial_stop        DECIMAL(12,4),
    current_stop        DECIMAL(12,4),
    initial_target      DECIMAL(12,4),
    current_target      DECIMAL(12,4),
    stop_adjustments    JSONB DEFAULT '[]',
    gross_pnl           DECIMAL(12,4),
    total_commission    DECIMAL(10,4) DEFAULT 0,
    net_pnl             DECIMAL(12,4),
    hold_seconds        DECIMAL(12,2),
    signal_to_fill_ms   DECIMAL(12,2),
    status              VARCHAR(10) NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING', 'OPEN', 'CLOSED', 'CANCELLED')),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades_v2(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_system ON trades_v2(system);
CREATE INDEX IF NOT EXISTS idx_trades_entry ON trades_v2(entry_time);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades_v2(status);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades_v2((entry_time::date));

-- ============================================================================
-- POSITIONS TABLE (Current State)
-- ============================================================================
CREATE TABLE IF NOT EXISTS positions (
    id                  SERIAL PRIMARY KEY,
    symbol              VARCHAR(10) NOT NULL,
    system              VARCHAR(20) NOT NULL,
    quantity            INTEGER NOT NULL DEFAULT 0,
    avg_price           DECIMAL(12,4),
    unrealized_pnl      DECIMAL(12,4) DEFAULT 0,
    realized_pnl        DECIMAL(12,4) DEFAULT 0,
    ibkr_quantity       INTEGER,
    ibkr_avg_price      DECIMAL(12,4),
    last_reconcile      TIMESTAMPTZ,
    is_reconciled       BOOLEAN DEFAULT FALSE,
    opened_at           TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, system)
);

CREATE INDEX IF NOT EXISTS idx_pos_symbol ON positions(symbol);

-- ============================================================================
-- SHARED POSITIONS TABLE (Cross-Service Position Awareness)
-- ============================================================================
CREATE TABLE IF NOT EXISTS shared_positions (
    service         VARCHAR(30) NOT NULL,
    symbol          VARCHAR(10) NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 0,
    avg_price       DECIMAL(12,4),
    margin_used     DECIMAL(12,4) DEFAULT 0,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (service, symbol)
);

CREATE INDEX IF NOT EXISTS idx_shared_pos_symbol ON shared_positions(symbol);
