"""Quantitative Performance & Risk Metrics Calculator."""

from dataclasses import dataclass
import math
import numpy as np

from src.simulator.portfolio import AccountSnapshot, Position


@dataclass
class BacktestMetrics:
    """Comprehensive performance and risk metrics report."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    
    # PnL & Payoff
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_profit: float = 0.0
    profit_factor: float = 0.0
    expected_payoff_usd: float = 0.0
    total_commission_usd: float = 0.0
    
    # Trade Averages
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0
    win_loss_ratio: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_trade_duration_seconds: float = 0.0
    
    # Portfolio & Risk Metrics
    initial_balance: float = 0.0
    final_equity: float = 0.0
    net_return_pct: float = 0.0
    max_drawdown_usd: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0


class MetricsCalculator:
    """Computes trade-by-trade and equity curve quantitative statistics."""

    @staticmethod
    def calculate(
        trades: list[Position],
        equity_curve: list[AccountSnapshot],
        initial_balance: float = 10_000.0,
        risk_free_rate: float = 0.0,
    ) -> BacktestMetrics:
        """Compute full statistical suite from executed trades and equity history."""
        m = BacktestMetrics(initial_balance=initial_balance)
        m.total_trades = len(trades)

        if m.total_trades == 0:
            m.final_equity = initial_balance
            return m

        # ---------------------------------------------------------
        # 1. Trade-level Analysis
        # ---------------------------------------------------------
        wins = [t.pnl_net for t in trades if t.pnl_net > 0]
        losses = [t.pnl_net for t in trades if t.pnl_net < 0]
        commissions = [t.commission for t in trades]

        m.winning_trades = len(wins)
        m.losing_trades = len(losses)
        m.win_rate_pct = round((m.winning_trades / m.total_trades) * 100.0, 2)

        m.gross_profit = round(sum(wins), 2)
        m.gross_loss = round(abs(sum(losses)), 2)
        m.net_profit = round(sum(t.pnl_net for t in trades), 2)
        m.total_commission_usd = round(sum(commissions), 2)

        if m.gross_loss > 0:
            m.profit_factor = round(m.gross_profit / m.gross_loss, 2)
        else:
            m.profit_factor = float("inf") if m.gross_profit > 0 else 0.0

        m.expected_payoff_usd = round(m.net_profit / m.total_trades, 2)

        m.avg_win_usd = round(sum(wins) / len(wins), 2) if wins else 0.0
        m.avg_loss_usd = round(abs(sum(losses)) / len(losses), 2) if losses else 0.0
        m.win_loss_ratio = round(m.avg_win_usd / m.avg_loss_usd, 2) if m.avg_loss_usd > 0 else 0.0

        # Consecutive streaks
        cur_win = max_win = 0
        cur_loss = max_loss = 0
        durations = []

        for t in trades:
            if t.pnl_net > 0:
                cur_win += 1
                cur_loss = 0
                max_win = max(max_win, cur_win)
            elif t.pnl_net < 0:
                cur_loss += 1
                cur_win = 0
                max_loss = max(max_loss, cur_loss)
            
            if t.close_time and t.open_time:
                durations.append((t.close_time - t.open_time).total_seconds())

        m.max_consecutive_wins = max_win
        m.max_consecutive_losses = max_loss
        m.avg_trade_duration_seconds = round(sum(durations) / len(durations), 2) if durations else 0.0

        # ---------------------------------------------------------
        # 2. Portfolio & Equity Curve Analysis
        # ---------------------------------------------------------
        if equity_curve:
            equities = np.array([snap.equity for snap in equity_curve])
            m.final_equity = round(float(equities[-1]), 2)
            m.net_return_pct = round(((m.final_equity - initial_balance) / initial_balance) * 100.0, 2)

            # Max Drawdown calculation
            peak = np.maximum.accumulate(equities)
            drawdown_usd = peak - equities
            m.max_drawdown_usd = round(float(np.max(drawdown_usd)), 2)

            drawdown_pct = np.where(peak > 0, (peak - equities) / peak, 0.0)
            m.max_drawdown_pct = round(float(np.max(drawdown_pct)) * 100.0, 2)

            # Sharpe & Sortino (based on step returns)
            if len(equities) > 1:
                returns = np.diff(equities) / equities[:-1]
                mean_ret = np.mean(returns)
                std_ret = np.std(returns)

                # Annualization factor for scalping (approx 252 trading days, intraday scale)
                # Using standard sqrt(N) scaling
                annualization_factor = math.sqrt(252 * 24 * 60) # sub-minute scale factor

                if std_ret > 1e-9:
                    m.sharpe_ratio = round(float((mean_ret - risk_free_rate) / std_ret * annualization_factor), 2)

                # Downside standard deviation (Sortino)
                downside_returns = returns[returns < 0]
                if len(downside_returns) > 0:
                    downside_std = np.std(downside_returns)
                    if downside_std > 1e-9:
                        m.sortino_ratio = round(float((mean_ret - risk_free_rate) / downside_std * annualization_factor), 2)

            if m.max_drawdown_pct > 0:
                m.calmar_ratio = round(m.net_return_pct / m.max_drawdown_pct, 2)

        return m
