from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app import models
from app.config import get_settings

_settings_cache: dict = {}

DEFAULTS = {
    "max_risk_per_trade_pct": "2.0",
    "max_risk_per_trade_abs": "",
    "max_daily_loss_pct": "5.0",
    "ai_confidence_threshold": "0.60",
    "min_risk_reward": "1.0",
    "default_mode": "paper",
    "manual_override": "false",
    "max_open_per_symbol": "7",
    "equity_balance": "10000.0",
}


async def _get_or_create(db: AsyncSession, key: str) -> models.SettingsTable:
    result = await db.execute(select(models.SettingsTable).where(models.SettingsTable.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        row = models.SettingsTable(key=key, value=DEFAULTS.get(key, ""))
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def get_setting(db: AsyncSession, key: str) -> str:
    row = await _get_or_create(db, key)
    return row.value or DEFAULTS.get(key, "")


async def get_setting_float(db: AsyncSession, key: str) -> float:
    val = await get_setting(db, key)
    try:
        return float(val) if val else float(DEFAULTS.get(key, "0"))
    except ValueError:
        return float(DEFAULTS.get(key, "0"))


async def get_setting_int(db: AsyncSession, key: str) -> int:
    val = await get_setting(db, key)
    try:
        return int(val) if val else int(DEFAULTS.get(key, "0"))
    except ValueError:
        return int(DEFAULTS.get(key, "0"))


async def get_setting_bool(db: AsyncSession, key: str) -> bool:
    val = await get_setting(db, key)
    return val.lower() == "true" if val else False


async def set_setting(db: AsyncSession, key: str, value: Any) -> None:
    str_val = str(value) if value is not None else ""
    result = await db.execute(select(models.SettingsTable).where(models.SettingsTable.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        row = models.SettingsTable(key=key, value=str_val)
        db.add(row)
    else:
        row.value = str_val
    await db.commit()


async def get_all_settings(db: AsyncSession) -> dict:
    out = {}
    for key, default in DEFAULTS.items():
        val = await get_setting(db, key)
        out[key] = val if val else default
    return out


async def build_settings_response(db: AsyncSession) -> dict:
    env = get_settings()
    all_db = await get_all_settings(db)
    result = await db.execute(select(models.ActivePair).order_by(models.ActivePair.priority))
    pairs = result.scalars().all()
    return {
        "default_pair": env.DEFAULT_PAIR,
        "max_risk_per_trade_pct": float(all_db.get("max_risk_per_trade_pct", "2.0")),
        "max_risk_per_trade_abs": float(all_db.get("max_risk_per_trade_abs", "0")) if all_db.get("max_risk_per_trade_abs") else None,
        "max_daily_loss_pct": float(all_db.get("max_daily_loss_pct", "5.0")),
        "ai_confidence_threshold": float(all_db.get("ai_confidence_threshold", "0.60")),
        "min_risk_reward": float(all_db.get("min_risk_reward", "1.0")),
        "default_mode": all_db.get("default_mode", "paper"),
        "manual_override": all_db.get("manual_override", "false").lower() == "true",
        "max_open_per_symbol": int(all_db.get("max_open_per_symbol", "7")),
        "equity_balance": float(all_db.get("equity_balance", "10000.0")),
        "active_pairs": [{"id": p.id, "symbol": p.symbol, "selection_mode": p.selection_mode, "priority": p.priority} for p in pairs],
    }
