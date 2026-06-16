"""Sprint 2 unit tests — Exit Optimization Layer."""
import pytest
from app.services.exit_evaluator import (
    ExitEvaluator, ExitRecommendation, ExitAction, compute_exit_quality_score
)
from app import models
from app.enums import TradeDirection, TradeStatus


class TestExitEvaluatorHelpers:
    def test_r_multiple_buy(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750, position_size=0.01,
        )
        r = ExitEvaluator()._compute_r_multiple(trade, 1.0850)
        assert abs(r - 1.0) < 0.05

    def test_max_favourable_r(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750,
            highest_price_seen=1.0900,
        )
        max_r = ExitEvaluator()._compute_max_favourable_r(trade)
        assert abs(max_r - 2.0) < 0.05


class TestProfitLockRule:
    @pytest.mark.asyncio
    async def test_profit_lock_triggers_on_giveback(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750,
            highest_price_seen=1.0900,
        )
        rec = await ExitEvaluator()._rule_profit_lock(trade, 1.0849, 50.0)
        assert rec is not None
        assert rec.action == ExitAction.CLOSE_NOW
        assert "profit_lock" in rec.reason

    @pytest.mark.asyncio
    async def test_profit_lock_no_trigger_before_2r(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750,
            highest_price_seen=1.0825,
        )
        rec = await ExitEvaluator()._rule_profit_lock(trade, 1.0800, 50.0)
        assert rec is None


class TestSLLadderRule:
    def test_breakeven_at_0_5r_buy(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750,
        )
        rec = ExitEvaluator()._rule_sl_ladder(trade, 1.0826)
        assert rec is not None
        assert rec.action == ExitAction.MOVE_SL
        assert rec.suggested_sl == 1.0800

    def test_sell_breakeven(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.SELL.value,
            entry_price=1.0850, stop_loss=1.0900,
        )
        rec = ExitEvaluator()._rule_sl_ladder(trade, 1.0824)
        assert rec is not None
        assert rec.suggested_sl == 1.0850


class TestPartialProfitRule:
    def test_partial_at_1r(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750,
        )
        rec = ExitEvaluator()._rule_partial_profit(trade, 1.0851)
        assert rec is not None
        assert rec.action == ExitAction.TAKE_PARTIAL
        assert rec.close_pct == 0.33

    def test_partial_at_1_5r(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750,
            closed_portion=0.33,
        )
        rec = ExitEvaluator()._rule_partial_profit(trade, 1.0876)
        assert rec is not None
        assert rec.action == ExitAction.TAKE_PARTIAL
        assert rec.close_pct == 0.33

    def test_no_partial_after_66_closed(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750,
            closed_portion=0.66,
        )
        rec = ExitEvaluator()._rule_partial_profit(trade, 1.0900)
        assert rec is None


class TestStalenessRule:
    def test_staleness_triggers(self):
        from datetime import datetime, timezone, timedelta
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750,
            open_time=datetime.now(timezone.utc) - timedelta(minutes=150),
        )
        rec = ExitEvaluator()._rule_staleness_with_price(trade, 1.0802, 120.0)
        assert rec is not None
        assert rec.action == ExitAction.CLOSE_NOW
        assert "staleness" in rec.reason

    def test_staleness_no_trigger_if_profitable(self):
        from datetime import datetime, timezone, timedelta
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750,
            open_time=datetime.now(timezone.utc) - timedelta(minutes=150),
        )
        rec = ExitEvaluator()._rule_staleness_with_price(trade, 1.0850, 120.0)
        assert rec is None


class TestExitQualityScore:
    def test_perfect_exit_score_high(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750, exit_price=1.0900,
            status=TradeStatus.CLOSED,
            pnl=100.0, peak_pnl=100.0,
            actual_holding_min=10.0,
        )
        score = compute_exit_quality_score(trade)
        assert score > 80

    def test_loss_exit_score_low(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750, exit_price=1.0750,
            status=TradeStatus.CLOSED,
            pnl=-50.0, peak_pnl=-10.0,
            actual_holding_min=5.0,
        )
        score = compute_exit_quality_score(trade)
        assert score < 50

    def test_partial_profit_bonus(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750, exit_price=1.0850,
            status=TradeStatus.CLOSED,
            pnl=50.0, peak_pnl=50.0,
            actual_holding_min=10.0,
            partial_tp_hit=True,
        )
        score_with = compute_exit_quality_score(trade)
        trade.partial_tp_hit = False
        score_without = compute_exit_quality_score(trade)
        assert score_with > score_without


class TestEvaluateTradeIntegration:
    @pytest.mark.asyncio
    async def test_disabled_rules_return_hold(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750,
        )
        rec = await ExitEvaluator().evaluate_trade(None, trade, 1.0850, {"exit_rules_enabled": False})
        assert rec.action == ExitAction.HOLD
        assert rec.reason == "exit_rules_disabled"

    @pytest.mark.asyncio
    async def test_sl_ladder_triggered_when_enabled(self):
        trade = models.Trade(
            symbol="EURUSD", direction=TradeDirection.BUY.value,
            entry_price=1.0800, stop_loss=1.0750,
        )
        rec = await ExitEvaluator().evaluate_trade(
            None, trade, 1.0826,
            {
                "exit_rules_enabled": True,
                "profit_lock_enabled": True,
                "profit_lock_giveback_pct": 50.0,
                "pre_news_exit_enabled": True,
                "technical_flip_enabled": True,
                "staleness_enabled": True,
                "staleness_max_min": 120.0,
                "sl_ladder_enabled": True,
                "partial_profit_enabled": True,
            }
        )
        assert rec.action == ExitAction.MOVE_SL
        assert "sl_ladder" in rec.reason
