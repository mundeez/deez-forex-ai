#!/usr/bin/env python3
"""Mini backtest: run 14 days to generate labeled production-suite data."""
import asyncio
import sys
sys.path.insert(0, "/app")

from datetime import datetime, timezone
from run_backtest_standalone import StandaloneBacktestEngine, ACTIVE_SYMBOLS

async def run_mini():
    engine = StandaloneBacktestEngine(initial_equity=200.0, run_id="mini_prod_v3")
    start = datetime(2025, 10, 15, tzinfo=timezone.utc)
    end = datetime(2025, 10, 29, tzinfo=timezone.utc)  # 14 days
    results = await engine.run(start, end, ACTIVE_SYMBOLS, strategy_mode="scalping", retrain_monthly=False)
    print("\n=== MINI BACKTEST COMPLETE ===")
    for k, v in results.items():
        print(f"  {k}: {v}")

if __name__ == "__main__":
    asyncio.run(run_mini())
