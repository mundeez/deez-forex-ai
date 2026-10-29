"""Per-variant accounting + lifecycle (Phase 7.1, plan §3.3 & §6).

Computes per-variant trade stats from closed trades, applies the
auto-retire criteria, snapshots `variant_stats`, and aggregates measured
execution costs from real spread/slippage columns into `execution_costs`.
"""
import logging
import math
from typing import Any, Dict, List

from sqlalchemy import select, func

from app import models
from app.database import get_celery_session

logger = logging.getLogger("app.services.variant_monitor")

KILL_LOSS_USD = -40.0          # -8R at fixed $5 risk (XAUUSD same cap per plan)
KILL_MIN_TRADES_EXP = 30       # >=30 trades and expectancy < 0
KILL_MIN_TRADES_PF = 60        # >=60 trades and PF < 1.15
PF_KILL_BAR = 1.15

PROMOTE_MIN_TRADES = 300
PROMOTE_T_STAT = 2.0
PROMOTE_PF_CI90 = 1.10
PROMOTE_MAX_DD_PCT = 0.10


def _stats(pnls: List[float]) -> Dict[str, Any]:
    n = len(pnls)
    if n == 0:
        return {"trades": 0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_w, gross_l = sum(wins), abs(sum(losses))
    pf = (gross_w / gross_l) if gross_l > 0 else (999.0 if gross_w > 0 else 0.0)
    mean = sum(pnls) / n
    var = sum((p - mean) ** 2 for p in pnls) / n
    sd = math.sqrt(var) or 1e-9
    t_stat = mean / (sd / math.sqrt(n))
    # max drawdown on the cumulative curve
    peak, mdd, cum = 0.0, 0.0, 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    # bootstrap-free PF CI approximation: log-PF SE via delta method
    wr = len(wins) / n
    avg_w = gross_w / len(wins) if wins else 0.0
    avg_l = gross_l / len(losses) if losses else 1e-9
    if n >= 20 and avg_w and avg_l:
        se_logpf = math.sqrt((1 - wr) / max(len(wins), 1) + wr / max(len(losses), 1))
        pf_ci90_low = math.exp(math.log(max(pf, 1e-9)) - 1.645 * se_logpf)
    else:
        pf_ci90_low = 0.0
    return {
        "trades": n, "wins": len(wins), "win_rate": wr,
        "profit_factor": round(pf, 3), "expectancy": round(mean, 4),
        "net_pnl": round(sum(pnls), 2), "max_drawdown": round(mdd, 2),
        "t_stat": round(t_stat, 3), "pf_ci90_low": round(pf_ci90_low, 3),
    }


async def compute_variant_stats() -> Dict[str, Any]:
    """Compute stats for every registered variant; apply kill criteria.

    XAUUSD trades are a SEPARATE bucket (plan §3.2): reported as their own
    variant_stats row (xauusd=true) and killed under their own -$40 cap via a
    Redis flag the engine checks at generation time — gold variance can
    neither contaminate FX stats nor keep a dead-gold variant firing.
    """
    from datetime import datetime, timezone
    import redis.asyncio as aioredis
    from app.config import get_settings
    r = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
    results = {}
    try:
        async with get_celery_session()() as db:
            variants = (await db.execute(select(models.StrategyVariant))).scalars().all()
            for v in variants:
                rows = (await db.execute(select(
                    models.Trade.symbol, models.Trade.pnl).where(
                        models.Trade.variant_id == v.variant_id,
                        models.Trade.status == models.TradeStatus.CLOSED,
                        models.Trade.pnl.isnot(None),
                    ))).all()
                fx_pnls = [float(p) for s, p in rows if s != "XAUUSD"]
                xau_pnls = [float(p) for s, p in rows if s == "XAUUSD"]
                for bucket, pnls in (("fx", fx_pnls), ("xau", xau_pnls)):
                    if bucket == "xau" and not pnls:
                        continue
                    st = _stats(pnls)
                    st["variant_id"] = v.variant_id
                    st["status"] = v.status
                    st["xauusd"] = bucket == "xau"

                    kill = None
                    if v.status == "active" and st.get("trades"):
                        if st["net_pnl"] <= KILL_LOSS_USD:
                            kill = f"{bucket} realized P&L ${st['net_pnl']:.2f} <= ${KILL_LOSS_USD:.0f} (-8R)"
                        elif st["trades"] >= KILL_MIN_TRADES_EXP and st["expectancy"] < 0:
                            kill = f"{bucket} {st['trades']} trades, expectancy {st['expectancy']} < 0"
                        elif st["trades"] >= KILL_MIN_TRADES_PF and (st["profit_factor"] or 0) < PF_KILL_BAR:
                            kill = f"{bucket} {st['trades']} trades, PF {st['profit_factor']} < {PF_KILL_BAR}"
                    if kill:
                        if bucket == "xau":
                            await r.set(f"variant:xau_kill:{v.variant_id}", kill, ex=30 * 86400)
                            logger.warning("VARIANT XAU KILL %s: %s", v.variant_id, kill)
                        else:
                            v.status = "retired"
                            v.retired_at = datetime.now(timezone.utc)
                            v.kill_reason = kill[:160]
                            logger.warning("VARIANT RETIRED %s: %s", v.variant_id, kill)
                        st["kill_reason"] = kill
                    promote = (
                        bucket == "fx" and v.status == "active"
                        and st.get("trades", 0) >= PROMOTE_MIN_TRADES
                        and (st.get("pf_ci90_low") or 0) > PROMOTE_PF_CI90
                        and (st.get("t_stat") or 0) > PROMOTE_T_STAT
                    )
                    st["promotable"] = bool(promote)
                    if promote:
                        logger.warning("VARIANT PROMOTABLE %s — meets section-6 bar", v.variant_id)

                    db.add(models.VariantStat(
                        variant_id=v.variant_id, trades=st.get("trades", 0),
                        wins=st.get("wins", 0), win_rate=st.get("win_rate"),
                        profit_factor=st.get("profit_factor"), expectancy=st.get("expectancy"),
                        net_pnl=st.get("net_pnl"), max_drawdown=st.get("max_drawdown"),
                        t_stat=st.get("t_stat"), pf_ci90_low=st.get("pf_ci90_low"),
                        xauusd=st["xauusd"],
                    ))
                    results[f"{v.variant_id}:{bucket}"] = st
            await db.commit()
    finally:
        await r.aclose()
    return results


async def aggregate_execution_costs() -> int:
    """Roll up measured spread/slippage from real trades into execution_costs."""
    async with get_celery_session()() as db:
        rows = (await db.execute(select(
            models.Trade.symbol,
            func.coalesce(models.Trade.session_at_open, 'unknown').label('session'),
            func.count().label('n'),
            func.avg(models.Trade.spread_at_entry).label('mean_spread'),
            func.avg(models.Trade.fill_slippage_pips).label('mean_in'),
            func.avg(models.Trade.exit_slippage_pips).label('mean_out'),
        ).where(
            models.Trade.status == models.TradeStatus.CLOSED,
            models.Trade.spread_at_entry.isnot(None),
        ).group_by(models.Trade.symbol, 'session'))).all()
        count = 0
        for sym, sess, n, ms, mi, mo in rows:
            db.add(models.ExecutionCost(
                symbol=sym, session=sess, samples=n,
                mean_spread_pips=ms, mean_entry_slip_pips=mi,
                mean_exit_slip_pips=mo))
            count += 1
        await db.commit()
        return count
