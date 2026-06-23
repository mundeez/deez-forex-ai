#!/usr/bin/env python3
"""Mini backtest: run 2 days to quickly generate labeled production-suite data."""
import asyncio
import sys
sys.path.insert(0, "/app")

from datetime import datetime, timezone
from run_backtest_standalone import StandaloneBacktestEngine, ACTIVE_SYMBOLS

async def run_mini():
    engine = StandaloneBacktestEngine(initial_equity=200.0, run_id="mini_prod_v2")
    start = datetime(2025, 10, 15, tzinfo=timezone.utc)
    end = datetime(2025, 10, 17, tzinfo=timezone.utc)  # 2 days only
    results = await engine.run(start, end, ACTIVE_SYMBOLS, strategy_mode="scalping", retrain_monthly=False)
    print("\n=== MINI BACKTEST COMPLETE ===")
    for k, v in results.items():
        print(f"  {k}: {v}")

if __name__ == "__main__":
    asyncio.run(run_mini())
