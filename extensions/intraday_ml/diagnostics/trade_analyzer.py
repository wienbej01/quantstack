"""Quantitative analyst for detailed trade analysis."""
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class TradeAnalyzer:
    """Analyze individual trades and identify patterns."""
    
    def __init__(self, trades_df: pd.DataFrame, config_id: int, config_params: dict[str, Any]):
        self.trades = trades_df
        self.config_id = config_id
        self.params = config_params
        self.analysis = {}
        
        # Calculate PnL if not present
        if 'pnl' not in self.trades.columns and 'r_multiple' in self.trades.columns:
            # Estimate PnL from r_multiple and price
            # PnL ≈ r_multiple * risk_amount (approximate)
            # For now, use r_multiple as proxy
            self.trades['pnl_proxy'] = self.trades['r_multiple']
        else:
            self.trades['pnl_proxy'] = self.trades.get('pnl', self.trades.get('r_multiple', 0))
    
    def analyze(self) -> dict[str, Any]:
        """Run full analysis suite."""
        if self.trades.empty:
            return {"config_id": self.config_id, "trades": 0, "analysis": "no_trades"}
        
        try:
            self.analysis = {
                "config_id": self.config_id,
                "params": self.params,
                "basic_stats": self._basic_stats(),
                "r_distribution": self._r_distribution(),
                "time_analysis": self._time_analysis(),
                "symbol_analysis": self._symbol_analysis(),
                "exit_reasons": self._exit_reasons(),
                "win_loss_patterns": self._win_loss_patterns(),
                "edge_analysis": self._edge_analysis(),
            }
        except Exception as e:
            logger.error(f"Analysis failed for config {self.config_id}: {e}")
            self.analysis = {
                "config_id": self.config_id,
                "error": str(e),
                "trades": len(self.trades)
            }
        
        return self.analysis
    
    def _basic_stats(self) -> dict[str, Any]:
        """Basic trade statistics."""
        return {
            "total_trades": len(self.trades),
            "win_rate": (self.trades['pnl_proxy'] > 0).mean(),
            "avg_pnl_proxy": self.trades['pnl_proxy'].mean(),
            "total_pnl_proxy": self.trades['pnl_proxy'].sum(),
            "avg_r": self.trades['r_multiple'].mean() if 'r_multiple' in self.trades.columns else None,
            "median_r": self.trades['r_multiple'].median() if 'r_multiple' in self.trades.columns else None,
            "max_win": self.trades['pnl_proxy'].max(),
            "max_loss": self.trades['pnl_proxy'].min(),
        }
    
    def _r_distribution(self) -> dict[str, Any]:
        """Analyze R-multiple distribution."""
        if 'r_multiple' not in self.trades.columns:
            return {}
        
        r_values = self.trades['r_multiple']
        return {
            "r_mean": float(r_values.mean()),
            "r_std": float(r_values.std()),
            "r_min": float(r_values.min()),
            "r_max": float(r_values.max()),
            "r_quartiles": {
                "q25": float(r_values.quantile(0.25)),
                "q50": float(r_values.quantile(0.50)),
                "q75": float(r_values.quantile(0.75)),
            },
            "pct_above_1r": float((r_values > 1.0).mean()),
            "pct_above_2r": float((r_values > 2.0).mean()),
            "pct_below_minus_1r": float((r_values < -1.0).mean()),
        }
    
    def _time_analysis(self) -> dict[str, Any]:
        """Analyze time-based patterns."""
        if 'timestamp' not in self.trades.columns:
            return {}
        
        try:
            self.trades['entry_hour'] = pd.to_datetime(self.trades['timestamp']).dt.hour
            hourly = self.trades.groupby('entry_hour').agg({
                'pnl_proxy': ['count', 'mean', 'sum'],
                'r_multiple': 'mean' if 'r_multiple' in self.trades.columns else 'count'
            })
            
            return {
                "trades_by_hour": hourly.to_dict(),
                "best_hour": int(self.trades.groupby('entry_hour')['pnl_proxy'].mean().idxmax()),
                "worst_hour": int(self.trades.groupby('entry_hour')['pnl_proxy'].mean().idxmin()),
            }
        except Exception as e:
            logger.warning(f"Time analysis failed: {e}")
            return {}
    
    def _symbol_analysis(self) -> dict[str, Any]:
        """Analyze per-symbol performance."""
        if 'symbol' not in self.trades.columns:
            return {}
        
        try:
            by_symbol = self.trades.groupby('symbol').agg({
                'pnl_proxy': ['count', 'mean', 'sum'],
                'r_multiple': 'mean' if 'r_multiple' in self.trades.columns else 'count'
            }).round(2)
            
            return {
                "unique_symbols": int(self.trades['symbol'].nunique()),
                "trades_per_symbol": by_symbol.to_dict(),
                "best_symbol": str(self.trades.groupby('symbol')['pnl_proxy'].sum().idxmax()),
                "worst_symbol": str(self.trades.groupby('symbol')['pnl_proxy'].sum().idxmin()),
            }
        except Exception as e:
            logger.warning(f"Symbol analysis failed: {e}")
            return {"unique_symbols": int(self.trades['symbol'].nunique())}
    
    def _exit_reasons(self) -> dict[str, Any]:
        """Analyze exit reasons."""
        if 'exit_reason' not in self.trades.columns:
            return {}
        
        try:
            exit_counts = self.trades['exit_reason'].value_counts().to_dict()
            exit_pnl = self.trades.groupby('exit_reason')['pnl_proxy'].agg(['count', 'mean', 'sum']).to_dict()
            
            return {
                "exit_counts": exit_counts,
                "exit_performance": exit_pnl,
            }
        except Exception as e:
            logger.warning(f"Exit reason analysis failed: {e}")
            return {}
    
    def _win_loss_patterns(self) -> dict[str, Any]:
        """Analyze win/loss streaks and patterns."""
        try:
            wins = (self.trades['pnl_proxy'] > 0).astype(int)
            
            # Calculate streaks
            streaks = []
            current_streak = 1
            for i in range(1, len(wins)):
                if wins.iloc[i] == wins.iloc[i-1]:
                    current_streak += 1
                else:
                    streaks.append(current_streak)
                    current_streak = 1
            streaks.append(current_streak)
            
            return {
                "max_win_streak": int(max([s for i, s in enumerate(streaks) if wins.iloc[min(i, len(wins)-1)] == 1], default=0)),
                "max_loss_streak": int(max([s for i, s in enumerate(streaks) if wins.iloc[min(i, len(wins)-1)] == 0], default=0)),
                "avg_streak_length": float(np.mean(streaks)) if streaks else 0,
            }
        except Exception as e:
            logger.warning(f"Win/loss pattern analysis failed: {e}")
            return {}
    
    def _edge_analysis(self) -> dict[str, Any]:
        """Calculate statistical edge."""
        if 'r_multiple' not in self.trades.columns:
            return {}
        
        try:
            win_rate = (self.trades['pnl_proxy'] > 0).mean()
            avg_win_r = self.trades[self.trades['pnl_proxy'] > 0]['r_multiple'].mean() if (self.trades['pnl_proxy'] > 0).any() else 0
            avg_loss_r = abs(self.trades[self.trades['pnl_proxy'] < 0]['r_multiple'].mean()) if (self.trades['pnl_proxy'] < 0).any() else 0
            
            expected_r = win_rate * avg_win_r - (1 - win_rate) * avg_loss_r
            
            return {
                "win_rate": float(win_rate),
                "avg_win_r": float(avg_win_r),
                "avg_loss_r": float(avg_loss_r),
                "expected_r": float(expected_r),
                "profit_factor": float(avg_win_r / avg_loss_r) if avg_loss_r > 0 else 0,
            }
        except Exception as e:
            logger.warning(f"Edge analysis failed: {e}")
            return {}
    
    def to_json(self) -> str:
        """Export analysis as JSON."""
        return json.dumps(self.analysis, indent=2, default=str)
    
    def to_summary(self) -> str:
        """Create human-readable summary."""
        if not self.analysis:
            return "No analysis available"
        
        basic = self.analysis.get('basic_stats', {})
        edge = self.analysis.get('edge_analysis', {})
        
        return f"""
Config {self.config_id} Analysis:
  Trades: {basic.get('total_trades', 0)}
  Win Rate: {basic.get('win_rate', 0):.1%}
  Avg R: {basic.get('avg_r', 0):.2f}
  Total PnL Proxy: {basic.get('total_pnl_proxy', 0):.2f}
  Expected R: {edge.get('expected_r', 0):.2f}
  Profit Factor: {edge.get('profit_factor', 0):.2f}
"""


def analyze_config_trades(config_row: pd.Series, trades_dir: Path) -> dict[str, Any]:
    """Analyze trades for a single configuration."""
    config_id = config_row['sweep_id']
    
    # Load trades (would need to be saved per config in sweep)
    # For now, return placeholder
    return {
        "config_id": config_id,
        "status": "pending",
        "note": "Trade-level data not saved per config in current sweep"
    }
