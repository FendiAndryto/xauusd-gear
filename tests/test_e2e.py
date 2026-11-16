"""End-to-End Pipeline Integration Test."""

from datetime import datetime, timezone
import polars as pl
import pytest

from scripts.run_pipeline import generate_synthetic_tick_sample
from src.analytics.metrics import MetricsCalculator
from src.analytics.reporting import PerformanceReporter
from src.analytics.validation import WalkForwardValidator
from src.config import BacktestConfig
from src.ingestion.storage import TickStorageManager
from src.simulator.engine import TickBacktestEngine
from src.strategies.micro_momentum import MicroMomentumScalper


def test_end_to_end_pipeline(tmp_path):
    # 1. Generate ticks
    df = generate_synthetic_tick_sample(n_ticks=2_000)
    assert len(df) == 2_000

    # 2. Persist to Parquet
    storage = TickStorageManager(base_dir=tmp_path / "parquet")
    saved = storage.save_ticks(df, symbol="XAUUSD")
    assert len(saved) > 0

    # 3. Read back from Parquet
    loaded_df = storage.load_ticks("XAUUSD")
    assert len(loaded_df) == 2_000

    # 4. Run Backtest Engine
    config = BacktestConfig(initial_balance=10_000.0)
    strategy = MicroMomentumScalper(window_size=10, momentum_threshold_usd=0.20)
    engine = TickBacktestEngine(strategy=strategy, config=config)
    res = engine.run(loaded_df, snapshot_interval_ticks=100)

    assert res.total_ticks_processed == 2_000
    assert len(res.equity_curve) > 0

    # 5. Compute Metrics
    metrics = MetricsCalculator.calculate(
        res.closed_trades, res.equity_curve, initial_balance=10_000.0
    )
    assert metrics.initial_balance == 10_000.0

    # 6. Report Export
    reporter = PerformanceReporter(output_dir=tmp_path / "reports")
    trade_file = reporter.export_trade_log(res.closed_trades)
    eq_file = reporter.export_equity_curve(res.equity_curve)

    assert trade_file.exists()
    assert eq_file.exists()

    # 7. WFA Validator
    validator = WalkForwardValidator(
        strategy_factory=lambda: MicroMomentumScalper(window_size=10, momentum_threshold_usd=0.20),
        config=config,
        train_ratio=0.70,
    )
    wfa_res = validator.evaluate(loaded_df)
    assert isinstance(wfa_res.is_robust, bool)
