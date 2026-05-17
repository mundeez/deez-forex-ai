"""Notification service for trade alerts via webhooks."""
import json
import logging
import httpx
from typing import Dict, Any, Optional
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.services.notifications")


class NotificationService:
    def __init__(self):
        self.webhook_url: Optional[str] = None
        self.discord_webhook: Optional[str] = None
        self.slack_webhook: Optional[str] = None
        self.pushover_token: Optional[str] = None
        self.pushover_user: Optional[str] = None

    async def _load_settings(self, db):
        from app.services.settings_service import get_setting
        self.webhook_url = await get_setting(db, "webhook_url")
        self.discord_webhook = await get_setting(db, "discord_webhook_url")
        self.slack_webhook = await get_setting(db, "slack_webhook_url")
        self.pushover_token = await get_setting(db, "pushover_app_token")
        self.pushover_user = await get_setting(db, "pushover_user_key")

    async def send_trade_opened(
        self, db, symbol: str, direction: str, entry_price: float, stop_loss: float,
        take_profit: float, position_size: float, strategy_mode: str, rationale: str = ""
    ):
        await self._load_settings(db)
        msg = (
            f"📈 Trade Opened: {symbol} {direction}\n"
            f"Entry: {entry_price:.5f} | SL: {stop_loss:.5f} | TP: {take_profit:.5f}\n"
            f"Size: {position_size:.2f} lots | Strategy: {strategy_mode}\n"
            f"Rationale: {rationale[:200]}"
        )
        await self._send_all(msg, title=f"Trade Opened: {symbol} {direction}")

    async def send_trade_closed(
        self, db, symbol: str, direction: str, entry_price: float, exit_price: float,
        pnl: float, pnl_pct: float, close_reason: str = ""
    ):
        await self._load_settings(db)
        emoji = "🟢" if pnl >= 0 else "🔴"
        msg = (
            f"{emoji} Trade Closed: {symbol} {direction}\n"
            f"Entry: {entry_price:.5f} | Exit: {exit_price:.5f}\n"
            f"PnL: ${pnl:.2f} ({pnl_pct:.2f}%)\n"
            f"Reason: {close_reason or 'N/A'}"
        )
        await self._send_all(msg, title=f"Trade Closed: {symbol} {pnl:+.2f}")

    async def send_alert(self, db, title: str, body: str):
        await self._load_settings(db)
        await self._send_all(f"{title}\n{body}", title=title)

    async def _send_all(self, text: str, title: str = "Deez Forex AI Alert"):
        tasks = []
        if self.discord_webhook:
            tasks.append(self._send_discord(text))
        if self.slack_webhook:
            tasks.append(self._send_slack(text))
        if self.pushover_token and self.pushover_user:
            tasks.append(self._send_pushover(title, text))
        if self.webhook_url:
            tasks.append(self._send_generic_webhook({"title": title, "message": text}))

        if tasks:
            import asyncio
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_discord(self, text: str):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    self.discord_webhook,
                    json={"content": text[:2000]},
                    headers={"Content-Type": "application/json"},
                )
        except Exception:
            logger.warning("Failed to send Discord notification", exc_info=True)

    async def _send_slack(self, text: str):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    self.slack_webhook,
                    json={"text": text[:4000]},
                    headers={"Content-Type": "application/json"},
                )
        except Exception:
            logger.warning("Failed to send Slack notification", exc_info=True)

    async def _send_pushover(self, title: str, text: str):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    "https://api.pushover.net/1/messages.json",
                    data={
                        "token": self.pushover_token,
                        "user": self.pushover_user,
                        "title": title[:250],
                        "message": text[:1024],
                    },
                )
        except Exception:
            logger.warning("Failed to send Pushover notification", exc_info=True)

    async def _send_generic_webhook(self, payload: Dict[str, Any]):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
        except Exception:
            logger.warning("Failed to send generic webhook notification", exc_info=True)
