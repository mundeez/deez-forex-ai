#!/usr/bin/env python3
"""Live paper trading monitor — run inside the backend container.

Usage: docker compose exec backend python3 /app/monitor_live.py
"""
import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
from app.database import get_celery_session


async def monitor():
    async with get_celery_session()() as db:
        print("=" * 70)
        print(f"LIVE PAPER TRADING MONITOR — {datetime.now(timezone.utc).isoformat()}")
        print("=" * 70)

        # --- Trades ---
        r = await db.execute(text("""
            SELECT count(*),
                   count(*) FILTER (WHERE status='CLOSED'),
                   count(*) FILTER (WHERE status='OPEN'),
                   count(*) FILTER (WHERE status='CLOSED' AND pnl > 0),
                   count(*) FILTER (WHERE status='CLOSED' AND pnl <= 0),
                   coalesce(sum(pnl) FILTER (WHERE status='CLOSED'), 0),
                   coalesce(avg(pnl) FILTER (WHERE status='CLOSED'), 0)
            FROM trades
        """))
        row = r.fetchone()
        total, closed, open_t, wins, losses, total_pnl, avg_pnl = row
        wr = (wins / closed * 100) if closed else 0
        print(f"\n--- TRADES ---")
        print(f"  Total: {total} | Closed: {closed} | Open: {open_t}")
        print(f"  Wins: {wins} | Losses: {losses} | Win Rate: {wr:.1f}%")
        print(f"  Total PnL: ${total_pnl:.2f} | Avg PnL: ${avg_pnl:.2f}")

        # --- Equity ---
        r = await db.execute(text("SELECT value FROM settings WHERE key='equity_balance'"))
        eq_row = r.fetchone()
        equity = float(eq_row[0]) if eq_row else 200.0
        current_equity = equity + total_pnl
        print(f"\n--- EQUITY ---")
        print(f"  Starting: ${equity:.2f} | Current: ${current_equity:.2f} | PnL: ${total_pnl:.2f}")

        # --- Recent Decisions ---
        r = await db.execute(text("""
            SELECT symbol, decision, confidence, timestamp
            FROM ai_decisions
            ORDER BY timestamp DESC
            LIMIT 10
        """))
        print(f"\n--- RECENT AI DECISIONS (last 10) ---")
        for row in r.fetchall():
            print(f"  {row[3]} | {row[0]:8s} | {row[1]:4s} | conf={row[2]:.2f}")

        # --- Open Positions ---
        if open_t > 0:
            r = await db.execute(text("""
                SELECT symbol, direction, entry_price, stop_loss, take_profit,
                       position_size, open_time, pnl
                FROM trades WHERE status='OPEN'
                ORDER BY open_time DESC
            """))
            print(f"\n--- OPEN POSITIONS ---")
            for row in r.fetchall():
                print(f"  {row[0]} | {row[1]} | entry={row[2]} | SL={row[3]} | TP={row[4]} | size={row[5]} | pnl={row[7]}")

        # --- Today's Trades ---
        r = await db.execute(text("""
            SELECT count(*), count(*) FILTER (WHERE pnl > 0),
                   coalesce(sum(pnl), 0)
            FROM trades
            WHERE status='CLOSED' AND close_time >= CURRENT_DATE
        """))
        row = r.fetchone()
        print(f"\n--- TODAY'S CLOSED TRADES ---")
        print(f"  Count: {row[0]} | Wins: {row[1]} | PnL: ${row[2]:.2f}")

        # --- Settings ---
        r = await db.execute(text("""
            SELECT key, value FROM settings
            WHERE key IN ('entry_gate_enabled','entry_gate_threshold',
                          'team_meta_enabled','memory_guard_enabled',
                          'paper_trading_mode','trading_enabled',
                          'decision_engine_version','strategy_mode',
                          'max_concurrent_live_trades','max_risk_per_trade_pct')
            ORDER BY key
        """))
        print(f"\n--- KEY SETTINGS ---")
        for row in r.fetchall():
            print(f"  {row[0]}: {row[1]}")

        # --- Retrain Status ---
        r = await db.execute(text("""
            SELECT count(*) FROM trades
            WHERE status='CLOSED' AND ai_decision_id IS NOT NULL
        """))
        retrain_count = r.scalar()
        next_retrain = 100 - (retrain_count % 100) if retrain_count > 0 else 100
        print(f"\n--- RETRAIN STATUS ---")
        print(f"  Closed trades with AI decisions: {retrain_count}")
        print(f"  Trades until next auto-retrain: {next_retrain}")
        print(f"  Weekly retrain: Sunday 02:00 UTC")

        print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(monitor())
