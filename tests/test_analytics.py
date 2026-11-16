"""Tests for statistical analytics, metrics calculator, and walk-forward validation."""

from datetime import datetime, timezone
import polars as pl
import pytest

from src.analytics.metrics import MetricsCalculator
from src.analytics.reporting import PerformanceReporter
from src.analytics.validation import WalkForwardValidator
from src.config import BacktestConfig
from src.simulator.portfolio import AccountSnapshot, Position
from src.strategies.base import BaseStrategy, TickEvent


def test_metrics_calculator_math():
    t0 = datetime(2024, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
    
    # 2 winning trades ($100 each), 1 losing trade (-$50)
    trades = [
        Position("1", "XAUUSD", "BUY", 1.0, t0, 2650.0, close_time=t0, close_price=2651.0, pnl_net=100.0, commission=6.0),
        Position("2", "XAUUSD", "BUY", 1.0, t0, 2650.0, close_time=t0, close_price=2651.0, pnl_net=100.0, commission=6.0),
        Position("3", "XAUUSD", "BUY", 1.0, t0, 2650.0, close_time=t0, close_price=2649.5, pnl_net=-50.0, commission=6.0),
    ]
    
    snaps = [
        AccountSnapshot(t0, balance=10_000.0, equity=10_000.0, used_margin=0, free_margin=10_000, margin_level_pct=0, open_positions_count=0),
        AccountSnapshot(t0, balance=10_150.0, equity=10_150.0, used_margin=0, free_margin=10_150, margin_level_pct=0, open_positions_count=0),
    ]

    m = MetricsCalculator.calculate(trades, snaps, initial_balance=10_000.0)

    assert m.total_trades == 3
    assert m.winning_trades == 2
    assert m.losing_trades == 1
    assert m.win_rate_pct == 66.67
    assert m.net_profit == 150.0
    assert m.gross_profit == 200.0
    assert m.gross_loss == 50.0
    assert m.profit_factor == 4.0
    assert m.expected_payoff_usd == 50.0
    assert m.total_commission_usd == 18.0


def test_reporting_export(tmp_path):
    reporter = PerformanceReporter(output_dir=tmp_path)
    t0 = datetime(2024, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
    trades = [
        Position("1", "XAUUSD", "BUY", 1.0, t0, 2650.0, close_time=t0, close_price=2651.0, pnl_net=100.0, commission=6.0)
    ]
    snaps = [
        AccountSnapshot(t0, balance=10_000.0, equity=10_100.0, used_margin=0, free_margin=10_100, margin_level_pct=0, open_positions_count=0)
    ]

    trade_file = reporter.export_trade_log(trades)
    assert trade_file.exists()
    assert "2650.0" in trade_file.read_text()

    eq_file = reporter.export_equity_curve(snaps)
    assert eq_file.exists()
    assert "10100.0" in eq_file.read_text()
