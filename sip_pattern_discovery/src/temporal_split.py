"""
Temporal data splitting for 3-period validation.
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Tuple


class TemporalSplit:
    """Split data into scan, validation, and OOS periods."""
    
    def __init__(
        self,
        scan_months: int = 7,
        validation_months: int = 2,
        oos_months: int = 1,
    ):
        self.scan_months = scan_months
        self.validation_months = validation_months
        self.oos_months = oos_months
    
    def split_data(
        self,
        df: pd.DataFrame,
        end_date: str = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Split data into scan/validation/OOS periods.
        
        Args:
            df: Full dataset with 'ts' column
            end_date: End date for OOS period (default: last date in df)
        
        Returns:
            (scan_df, validation_df, oos_df)
        """
        df = df.copy()
        df['date'] = pd.to_datetime(df['ts']).dt.date
        
        if end_date is None:
            end_date = df['date'].max()
        else:
            end_date = pd.to_datetime(end_date).date()
        
        # Calculate period boundaries
        oos_start = end_date - timedelta(days=30 * self.oos_months)
        val_start = oos_start - timedelta(days=30 * self.validation_months)
        scan_start = val_start - timedelta(days=30 * self.scan_months)
        
        # Split
        scan_df = df[(df['date'] >= scan_start) & (df['date'] < val_start)]
        val_df = df[(df['date'] >= val_start) & (df['date'] < oos_start)]
        oos_df = df[(df['date'] >= oos_start) & (df['date'] <= end_date)]
        
        return scan_df, val_df, oos_df
    
    def get_period_info(self, df: pd.DataFrame, end_date: str = None) -> dict:
        """Get information about the split periods."""
        scan_df, val_df, oos_df = self.split_data(df, end_date)
        
        return {
            'scan': {
                'start': scan_df['date'].min(),
                'end': scan_df['date'].max(),
                'days': len(scan_df['date'].unique()),
                'bars': len(scan_df),
            },
            'validation': {
                'start': val_df['date'].min(),
                'end': val_df['date'].max(),
                'days': len(val_df['date'].unique()),
                'bars': len(val_df),
            },
            'oos': {
                'start': oos_df['date'].min(),
                'end': oos_df['date'].max(),
                'days': len(oos_df['date'].unique()),
                'bars': len(oos_df),
            },
        }
