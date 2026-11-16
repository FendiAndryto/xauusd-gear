"""Standalone 11-Month Tick Benchmark for AsianCloseBreakoutStrategy.

Runs strictly isolated on Exness institutional tick data (Jan - Nov 2026)
with realistic 50-120 ms stochastic latency, dynamic spread, and slippage.
"""

import argparse
import gc
from pathlib import Path
import sys
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl
from rich.console import Console
from rich.table import Table

from src.analytics.metrics import MetricsCalculator
from src.config import BacktestConfig, BrokerConfig, ExecutionConfig
from src.simulator.engine import TickBacktestEngine
from src.strategies.asian_close_breakout import AsianCloseBreakoutStrategy

console = Console(width=160)

MONTH_NAMES = {
    "01": "Januari 2026",
    "02": "Februari 2026",
    "03": "Maret 2026",
    "04": "April 2026",
    "05": "Mei 2026",
    "06": "Juni 2026",
    "07": "Juli 2026",
    "08": "Agustus 2026",
    "09": "September 2026",
    "10": "Oktober 2026",
    "11": "November 2026",
}


def get_default_config(initial_balance: float = 10_000.0) -> BacktestConfig:
    broker_cfg = BrokerConfig(
        symbol="XAUUSDm",
        contract_size=100.0,
        point_size=0.001,
        digits=3,
        commission_per_lot_round_turn=0.0,
    )
    exec_cfg = ExecutionConfig(
        latency_min_ms=50,
        latency_max_ms=120,
        base_slippage_mean_points=0.01,
        base_slippage_std_points=0.02,
    )
    return BacktestConfig(
        initial_balance=initial_balance,
        broker=broker_cfg,
        execution=exec_cfg,
    )


def run_benchmark(
    months: list[str],
    start_balance: float = 10_000.0,
    buffer_usd: float = 1.0,
    max_asian_range: float = 120.0,
    risk_pct: float = 0.01,
    htf_filter: bool = True,
    aligned_risk: float = 0.0125,
    counter_risk: float = 0.0035,
    tp_mult: Optional[float] = None,
    close_hour: int = 20,
    close_min: int = 55,
):
    console.print("[bold cyan]====================================================================[/bold cyan]")
    console.print("[bold cyan]  STANDALONE ASIAN CLOSE BREAKOUT TICK BENCHMARK (JAN - NOV 2026)  [/bold cyan]")
    tp_str = f"TP={tp_mult:.2f}R" if tp_mult is not None else f"NO-TP (Session Close {close_hour:02d}:{close_min:02d} UTC)"
    console.print(f"[bold cyan]  SL=0.50R (Asian EQ) | {tp_str} | Buf=${buffer_usd:.1f} | RiskScale ({aligned_risk*100:.2f}%/{counter_risk*100:.2f}%) [/bold cyan]")
    console.print("[bold cyan]====================================================================[/bold cyan]")

    current_equity = start_balance
    peak_equity_overall = start_balance
    max_dd_overall_pct = 0.0
    monthly_records = []
    ema50 = None
    ema200 = None
    h1_bars_count = 0

    for m in months:
        month_files = sorted(Path(f"data/parquet/xauusd/year=2026/month={m}").glob("*.parquet"))
        if not month_files:
            console.print(f"[yellow]Skipping month {m}: No parquet files found.[/yellow]")
            continue

        df = pl.read_parquet(month_files).sort("timestamp")
        if "spread" not in df.columns:
            df = df.with_columns((pl.col("ask") - pl.col("bid")).alias("spread"))
        if "volume" not in df.columns:
            df = df.with_columns(pl.lit(0.0).alias("volume"))
        n_ticks = len(df)

        strategy = AsianCloseBreakoutStrategy(
            buffer_usd=buffer_usd,
            sl_range_mult=0.50,
            tp_range_mult=tp_mult,
            risk_per_trade_pct=risk_pct,
            htf_filter_enabled=htf_filter,
            aligned_risk_pct=aligned_risk,
            counter_risk_pct=counter_risk,
            min_asian_range=5.0,
            max_asian_range=max_asian_range,
            session_close_hour_utc=close_hour,
            session_close_minute_utc=close_min,
        )
        strategy.seed_ema_state(ema50, ema200, h1_bars_count)

        cfg = get_default_config(initial_balance=current_equity)
        engine = TickBacktestEngine(strategy=strategy, config=cfg)
        result = engine.run(df)
        ema50, ema200, h1_bars_count = strategy.get_ema_state()

        m_metrics = MetricsCalculator.calculate(result.closed_trades, result.equity_curve, current_equity)

        # Track cumulative max DD across all months
        for snap in result.equity_curve:
            if snap.equity > peak_equity_overall:
                peak_equity_overall = snap.equity
            dd_pct = ((peak_equity_overall - snap.equity) / peak_equity_overall) * 100.0 if peak_equity_overall > 0 else 0.0
            if dd_pct > max_dd_overall_pct:
                max_dd_overall_pct = dd_pct

        trades_df = (
            pl.DataFrame([{"side": t.side, "pnl": t.pnl_net} for t in result.closed_trades])
            if len(result.closed_trades) > 0
            else pl.DataFrame()
        )

        buys = trades_df.filter(pl.col("side") == "BUY") if len(trades_df) > 0 else pl.DataFrame()
        sells = trades_df.filter(pl.col("side") == "SELL") if len(trades_df) > 0 else pl.DataFrame()

        buy_count = len(buys)
        sell_count = len(sells)
        buy_pnl = float(buys["pnl"].sum()) if buy_count > 0 else 0.0
        sell_pnl = float(sells["pnl"].sum()) if sell_count > 0 else 0.0

        pnl = m_metrics.net_profit
        start_bal = current_equity
        end_bal = round(current_equity + pnl, 2)
        current_equity = end_bal
        ret_pct = (pnl / start_bal) * 100.0 if start_bal > 0 else 0.0
        status = "PROFIT" if pnl > 0 else ("PROTECTED" if pnl == 0.0 else "DEFICIT")

        rec = {
            "month_code": m,
            "month_name": MONTH_NAMES.get(m, f"Month {m}"),
            "ticks": n_ticks,
            "start_balance": start_bal,
            "net_pnl": pnl,
            "end_balance": end_bal,
            "return_pct": ret_pct,
            "max_dd_pct": m_metrics.max_drawdown_pct,
            "total_trades": m_metrics.total_trades,
            "win_rate": m_metrics.win_rate_pct,
            "profit_factor": m_metrics.profit_factor,
            "buy_count": buy_count,
            "buy_pnl": buy_pnl,
            "sell_count": sell_count,
            "sell_pnl": sell_pnl,
            "status": status,
        }
        monthly_records.append(rec)

        console.print(
            f"[green]Month {m} ({n_ticks:,} ticks): PnL=${pnl:+,.2f} | End=${end_bal:,.2f} | "
            f"Trades={m_metrics.total_trades} | WR={m_metrics.win_rate_pct:.1f}% | PF={m_metrics.profit_factor:.2f} | {status}[/green]"
        )

        del df, result, engine, strategy
        gc.collect()

    # Print Summary Table
    table = Table(title="Continuous Monthly Equity Carryover (Standalone Asian Close Breakout)")
    for col in ["Bulan", "Modal Awal", "Net PnL", "Modal Akhir", "Return%", "MaxDD%", "Trades", "WR%", "PF", "BUY (N/$)", "SELL (N/$)", "Status"]:
        table.add_column(col, justify="right" if col not in ("Bulan", "Status") else "left")

    for r in monthly_records:
        table.add_row(
            r["month_name"],
            f"${r['start_balance']:,.2f}",
            f"${r['net_pnl']:+,.2f}",
            f"${r['end_balance']:,.2f}",
            f"{r['return_pct']:+.2f}%",
            f"{r['max_dd_pct']:.2f}%",
            str(r["total_trades"]),
            f"{r['win_rate']:.1f}%",
            f"{r['profit_factor']:.2f}",
            f"{r['buy_count']} (${r['buy_pnl']:+,.0f})",
            f"{r['sell_count']} (${r['sell_pnl']:+,.0f})",
            r["status"],
        )

    console.print(table)
    tot_net = current_equity - start_balance
    tot_ret = (tot_net / start_balance) * 100.0
    pos_months = sum(1 for r in monthly_records if r["net_pnl"] > 0)
    console.print(
        f"\n[bold]Portfolio Start: ${start_balance:,.2f} -> End: ${current_equity:,.2f} | "
        f"Total Net: ${tot_net:+,.2f} ({tot_ret:+.2f}%) | Max DD Kumulatif: {max_dd_overall_pct:.2f}% | "
        f"Bulan Profit: {pos_months}/{len(monthly_records)}[/bold]"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", nargs="+", default=["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11"])
    parser.add_argument("--buffer", type=float, default=1.0)
    parser.add_argument("--max-range", type=float, default=120.0)
    parser.add_argument("--risk", type=float, default=0.01)
    parser.add_argument("--no-htf", action="store_true", default=False)
    parser.add_argument("--aligned-risk", type=float, default=0.0125)
    parser.add_argument("--counter-risk", type=float, default=0.0035)
    parser.add_argument("--no-tp", action="store_true", default=False)
    parser.add_argument("--tp-mult", type=float, default=1.0)
    parser.add_argument("--close-hour", type=int, default=20)
    parser.add_argument("--close-min", type=int, default=55)
    args = parser.parse_args()
    tp_val = None if args.no_tp else args.tp_mult
    run_benchmark(
        args.months,
        buffer_usd=args.buffer,
        max_asian_range=args.max_range,
        risk_pct=args.risk,
        htf_filter=not args.no_htf,
        aligned_risk=args.aligned_risk,
        counter_risk=args.counter_risk,
        tp_mult=tp_val,
        close_hour=args.close_hour,
        close_min=args.close_min,
    )
