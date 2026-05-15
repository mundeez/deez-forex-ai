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
    "equity_balance": "100.0",
    "strategy_mode": "scalping",
    "max_trade_duration_min": "10",
    "eod_close_enabled": "true",
    "eod_close_time_utc": "21:30",
    "eod_no_new_entries_before": "21:00",
    "weekend_close_enabled": "true",
    "weekend_close_time_utc": "21:00",
    "weekend_resume_time_utc": "22:00",
    "enable_technical": "true",
    "enable_fundamental": "true",
    "enable_sentiment": "true",
    "chart_refresh_ms": "30000",
    "analysis_poll_ms": "15000",
    "trailing_stop_enabled": "true",
    "trailing_stop_distance_atr": "1.0",
    "trailing_stop_activation_atr": "1.0",
    "partial_profit_enabled": "true",
    "partial_profit_pct": "50.0",
    "partial_profit_r_multiple": "1.0",
    "spread_filter_enabled": "true",
    "max_spread_to_atr_ratio": "0.30",
    "drawdown_guard_enabled": "true",
    "drawdown_reduce_10pct": "50.0",
    "drawdown_reduce_20pct": "75.0",
    "drawdown_block_30pct": "true",
    "correlation_guard_enabled": "true",
    "max_correlation_allowed": "0.75",
    "batched_ai_enabled": "false",
    "auto_strategy_switch_enabled": "false",
    "news_halt_enabled": "true",
    "news_halt_buffer_before_min": "15",
    "news_halt_buffer_after_min": "30",
    "webhook_url": "",
    "discord_webhook_url": "",
    "slack_webhook_url": "",
    "pushover_app_token": "",
    "pushover_user_key": "",
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
        "data_provider": env.DATA_PROVIDER.value,
        "strategy_mode": all_db.get("strategy_mode", "scalping"),
        "max_risk_per_trade_pct": float(all_db.get("max_risk_per_trade_pct", "2.0")),
        "max_risk_per_trade_abs": float(all_db.get("max_risk_per_trade_abs", "0")) if all_db.get("max_risk_per_trade_abs") else None,
        "max_daily_loss_pct": float(all_db.get("max_daily_loss_pct", "5.0")),
        "ai_confidence_threshold": float(all_db.get("ai_confidence_threshold", "0.60")),
        "min_risk_reward": float(all_db.get("min_risk_reward", "1.0")),
        "default_mode": all_db.get("default_mode", "paper"),
        "manual_override": all_db.get("manual_override", "false").lower() == "true",
        "max_open_per_symbol": int(all_db.get("max_open_per_symbol", "7")),
        "equity_balance": float(all_db.get("equity_balance", "100.0")),
        "max_trade_duration_min": int(all_db.get("max_trade_duration_min", "10")),
        "eod_close_enabled": all_db.get("eod_close_enabled", "true").lower() == "true",
        "eod_close_time_utc": all_db.get("eod_close_time_utc", "21:30"),
        "eod_no_new_entries_before": all_db.get("eod_no_new_entries_before", "21:00"),
        "weekend_close_enabled": all_db.get("weekend_close_enabled", "true").lower() == "true",
        "weekend_close_time_utc": all_db.get("weekend_close_time_utc", "21:00"),
        "weekend_resume_time_utc": all_db.get("weekend_resume_time_utc", "22:00"),
        "enable_technical": all_db.get("enable_technical", "true").lower() == "true",
        "enable_fundamental": all_db.get("enable_fundamental", "true").lower() == "true",
        "enable_sentiment": all_db.get("enable_sentiment", "true").lower() == "true",
        "chart_refresh_ms": int(all_db.get("chart_refresh_ms", "30000")),
        "analysis_poll_ms": int(all_db.get("analysis_poll_ms", "15000")),
        "active_pairs": [{"id": p.id, "symbol": p.symbol, "selection_mode": p.selection_mode, "priority": p.priority} for p in pairs],
        "trailing_stop_enabled": all_db.get("trailing_stop_enabled", "true").lower() == "true",
        "trailing_stop_distance_atr": float(all_db.get("trailing_stop_distance_atr", "1.0")),
        "partial_profit_enabled": all_db.get("partial_profit_enabled", "true").lower() == "true",
        "partial_profit_pct": float(all_db.get("partial_profit_pct", "50.0")),
        "spread_filter_enabled": all_db.get("spread_filter_enabled", "true").lower() == "true",
        "max_spread_to_atr_ratio": float(all_db.get("max_spread_to_atr_ratio", "0.30")),
        "drawdown_guard_enabled": all_db.get("drawdown_guard_enabled", "true").lower() == "true",
        "correlation_guard_enabled": all_db.get("correlation_guard_enabled", "true").lower() == "true",
        "batched_ai_enabled": all_db.get("batched_ai_enabled", "false").lower() == "true",
        "auto_strategy_switch_enabled": all_db.get("auto_strategy_switch_enabled", "false").lower() == "true",
        "news_halt_enabled": all_db.get("news_halt_enabled", "true").lower() == "true",
        "news_halt_buffer_before_min": int(all_db.get("news_halt_buffer_before_min", "15")),
        "news_halt_buffer_after_min": int(all_db.get("news_halt_buffer_after_min", "30")),
        "webhook_url": all_db.get("webhook_url", ""),
        "discord_webhook_url": all_db.get("discord_webhook_url", ""),
        "slack_webhook_url": all_db.get("slack_webhook_url", ""),
        "pushover_app_token": all_db.get("pushover_app_token", ""),
        "pushover_user_key": all_db.get("pushover_user_key", ""),
    }
