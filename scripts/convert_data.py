import glob
from pathlib import Path

import pandas as pd
import polars as pl

DATA_DIR = Path("/home/wh/Documents/Data/stocks_1m")
OUTPUT_FILE = Path("/home/wh/Documents/Data/prices.parquet")

def process():
    csv_files = glob.glob(str(DATA_DIR / "*.csv"))
    if not csv_files:
        print("No CSV files found.")
        return
        
    dfs = []
    for f in csv_files:
        print(f"Reading {f}...")
        df = pd.read_csv(f)
        # Columns: order_book_id,datetime,num_trades,low,high,open,close,volume,total_turnover
        # Ensure datetime is parsed
        df['datetime'] = pd.to_datetime(df['datetime'])
        # Set datetime as index for resampling
        df.set_index('datetime', inplace=True)
        
        # Resample to daily
        daily_df = df.resample('D').agg({
            'order_book_id': 'first',
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
            'total_turnover': 'sum'
        }).dropna(subset=['order_book_id', 'close'])
        
        daily_df.reset_index(inplace=True)
        daily_df.rename(columns={
            'datetime': 'trade_date',
            'order_book_id': 'ts_code',
            'total_turnover': 'amount'
        }, inplace=True)
        
        dfs.append(daily_df)
        
    final_df = pd.concat(dfs, ignore_index=True)
    
    # Save as parquet using Polars for strict types
    pldf = pl.from_pandas(final_df)
    pldf = pldf.with_columns(pl.col('trade_date').dt.date())
    
    pldf.write_parquet(OUTPUT_FILE)
    print(f"Successfully wrote {len(pldf)} daily records to {OUTPUT_FILE}")

if __name__ == "__main__":
    process()
