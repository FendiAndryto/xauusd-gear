"""Reporting and Tear-sheet Generator using Rich console and CSV/Parquet export."""

from datetime import datetime
from pathlib import Path
from typing import Optional
import polars as pl
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.analytics.metrics import BacktestMetrics
from src.config import PathConfig
from src.simulator.portfolio import AccountSnapshot, Position


class PerformanceReporter:
    """Formats and exports comprehensive backtest reports."""

    def __init__(self, output_dir: Optional[Path] = None):
        paths = PathConfig()
        self.output_dir = output_dir or paths.reports_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.console = Console()

    def print_tear_sheet(self, metrics: BacktestMetrics, title: str = "XAUUSD Scalping Performance Summary"):
        """Render a formatted tear-sheet table in the terminal console."""
        # 1. Main Metrics Table
        table = Table(title=title, show_header=True, header_style="bold cyan", border_style="bright_blue")
        table.add_column("Metric", style="dim", width=32)
        table.add_column("Value", justify="right", style="bold")

        # Portfolio returns
        table.add_row("Initial Balance", f"${metrics.initial_balance:,.2f}")
        table.add_row("Final Equity", f"${metrics.final_equity:,.2f}")
        
        profit_color = "green" if metrics.net_profit >= 0 else "red"
        table.add_row("Net Profit", f"[{profit_color}]${metrics.net_profit:,.2f}[/{profit_color}]")
        table.add_row("Return (%)", f"[{profit_color}]{metrics.net_return_pct:+.2f}%[/{profit_color}]")
        table.add_row("Total Commission Paid", f"${metrics.total_commission_usd:,.2f}")
        table.add_section()

        # Trade stats
        table.add_row("Total Trades Executed", f"{metrics.total_trades:,}")
        table.add_row("Win Rate", f"{metrics.win_rate_pct:.1f}% ({metrics.winning_trades}W / {metrics.losing_trades}L)")
        table.add_row("Profit Factor (Gross P/L)", f"{metrics.profit_factor:.2f}")
        table.add_row("Expected Payoff per Trade", f"${metrics.expected_payoff_usd:.2f}")
        table.add_row("Average Win / Loss", f"${metrics.avg_win_usd:.2f} / ${metrics.avg_loss_usd:.2f}")
        table.add_row("Win/Loss Ratio", f"{metrics.win_loss_ratio:.2f}")
        table.add_row("Max Consecutive Wins / Losses", f"{metrics.max_consecutive_wins} / {metrics.max_consecutive_losses}")
        table.add_row("Avg Trade Duration", f"{metrics.avg_trade_duration_seconds:.1f} sec")
        table.add_section()

        # Risk & Volatility
        dd_color = "red" if metrics.max_drawdown_pct > 10.0 else "yellow"
        table.add_row("Max Drawdown ($)", f"[{dd_color}]${metrics.max_drawdown_usd:,.2f}[/{dd_color}]")
        table.add_row("Max Drawdown (%)", f"[{dd_color}]{metrics.max_drawdown_pct:.2f}%[/{dd_color}]")
        table.add_row("Sharpe Ratio (Annualized)", f"{metrics.sharpe_ratio:.2f}")
        table.add_row("Sortino Ratio", f"{metrics.sortino_ratio:.2f}")
        table.add_row("Calmar Ratio", f"{metrics.calmar_ratio:.2f}")

        self.console.print(table)

    def export_trade_log(self, trades: list[Position], filename: str = "trades.csv") -> Path:
        """Export all executed trade records to CSV."""
        if not trades:
            out_path = self.output_dir / filename
            out_path.write_text("No trades recorded.\n", encoding="utf-8")
            return out_path

        records = []
        for t in trades:
            records.append({
                "position_id": t.position_id,
                "symbol": t.symbol,
                "side": t.side,
                "volume": t.volume,
                "open_time": str(t.open_time),
                "open_price": t.open_price,
                "close_time": str(t.close_time),
                "close_price": t.close_price,
                "close_reason": t.close_reason,
                "commission": t.commission,
                "pnl_gross": t.pnl_gross,
                "pnl_net": t.pnl_net,
                "comment": t.comment,
            })

        df = pl.DataFrame(records)
        out_path = self.output_dir / filename
        df.write_csv(out_path)
        return out_path

    def export_equity_curve(self, snapshots: list[AccountSnapshot], filename: str = "equity_curve.csv") -> Path:
        """Export equity time-series curve to CSV."""
        if not snapshots:
            out_path = self.output_dir / filename
            out_path.write_text("No snapshots.\n", encoding="utf-8")
            return out_path

        records = [{
            "timestamp": str(s.timestamp),
            "balance": s.balance,
            "equity": s.equity,
            "used_margin": s.used_margin,
            "free_margin": s.free_margin,
            "margin_level_pct": s.margin_level_pct,
            "open_positions_count": s.open_positions_count,
        } for s in snapshots]

        df = pl.DataFrame(records)
        out_path = self.output_dir / filename
        df.write_csv(out_path)
        return out_path
