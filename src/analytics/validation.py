"""Walk-Forward Analysis (WFA) and Anti-Overfitting Validation Engine."""

from dataclasses import dataclass
from typing import Callable, Optional
import polars as pl

from src.analytics.metrics import BacktestMetrics, MetricsCalculator
from src.config import BacktestConfig
from src.simulator.engine import TickBacktestEngine
from src.strategies.base import BaseStrategy


@dataclass
class WFAResult:
    """Results of Walk-Forward / Out-of-Sample evaluation."""
    in_sample_metrics: BacktestMetrics
    out_of_sample_metrics: BacktestMetrics
    sharpe_degradation_ratio: float
    profit_factor_degradation_ratio: float
    win_rate_degradation_ratio: float
    is_robust: bool
    status_summary: str


class WalkForwardValidator:
    """Splits tick data chronologically into In-Sample and Out-of-Sample to test robustness."""

    def __init__(
        self,
        strategy_factory: Callable[[], BaseStrategy],
        config: Optional[BacktestConfig] = None,
        train_ratio: float = 0.70,
        min_sharpe_degradation: float = 0.60,
    ):
        self.strategy_factory = strategy_factory
        self.config = config or BacktestConfig()
        self.train_ratio = train_ratio
        self.min_sharpe_degradation = min_sharpe_degradation

    def evaluate(self, ticks_df: pl.DataFrame) -> WFAResult:
        """Run In-Sample and Out-of-Sample backtests and compare degradation."""
        total_ticks = len(ticks_df)
        split_idx = int(total_ticks * self.train_ratio)

        is_df = ticks_df.slice(0, split_idx)
        oos_df = ticks_df.slice(split_idx, total_ticks - split_idx)

        # 1. Run In-Sample
        is_strategy = self.strategy_factory()
        is_engine = TickBacktestEngine(strategy=is_strategy, config=self.config)
        is_sim = is_engine.run(is_df)
        is_metrics = MetricsCalculator.calculate(
            is_sim.closed_trades, is_sim.equity_curve, self.config.initial_balance
        )

        # 2. Run Out-of-Sample
        oos_strategy = self.strategy_factory()
        oos_engine = TickBacktestEngine(strategy=oos_strategy, config=self.config)
        oos_sim = oos_engine.run(oos_df)
        oos_metrics = MetricsCalculator.calculate(
            oos_sim.closed_trades, oos_sim.equity_curve, self.config.initial_balance
        )

        # 3. Compute Degradation Ratios
        sharpe_ratio = (
            round(oos_metrics.sharpe_ratio / is_metrics.sharpe_ratio, 2)
            if is_metrics.sharpe_ratio > 0
            else 0.0
        )
        pf_ratio = (
            round(oos_metrics.profit_factor / is_metrics.profit_factor, 2)
            if is_metrics.profit_factor > 0
            else 0.0
        )
        wr_ratio = (
            round(oos_metrics.win_rate_pct / is_metrics.win_rate_pct, 2)
            if is_metrics.win_rate_pct > 0
            else 0.0
        )

        # 4. Check Robustness
        is_robust = (
            oos_metrics.net_profit > 0
            and oos_metrics.profit_factor >= 1.2
            and (sharpe_ratio >= self.min_sharpe_degradation or oos_metrics.sharpe_ratio >= 1.5)
        )

        status = "PASSED: Strategy demonstrates robust out-of-sample edge." if is_robust else "FAILED: Severe degradation or negative PnL in Out-of-Sample (Overfitting detected)."

        return WFAResult(
            in_sample_metrics=is_metrics,
            out_of_sample_metrics=oos_metrics,
            sharpe_degradation_ratio=sharpe_ratio,
            profit_factor_degradation_ratio=pf_ratio,
            win_rate_degradation_ratio=wr_ratio,
            is_robust=is_robust,
            status_summary=status,
        )
