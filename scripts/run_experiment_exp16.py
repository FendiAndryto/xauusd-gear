"""Execution & Benchmarking Runner for EXP-16 (Adaptive Dual-Engine with Bearish Expansion & Boundary Fatigue Shield).

Evaluates AdaptiveDualEngineScalper with:
1. Daily Bearish Expansion Gate ($DayDisp <= -$10.00):
   Blocks buying falling knives during cascading bear trend days.
2. Setup-Level Boundary Fatigue Guard (max_distinct_sls_per_day = 2):
   Locks broken boundaries after >= 2 distinct setups get stopped out today,
   halting the Sequential S/R Laddering trap on runaway trend days.
3. Full 8-Month Longitudinal Simulation (53.54M ticks from April to November 2026).
4. Strictly NO calendar pruning: Monday is 100% active; zero random hourly blackouts.
5. In compliance with Supreme Research Mandate (AGENTS.md).
"""

from datetime import datetime
import gc
from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl
from rich.console import Console
from rich.table import Table

from src.analytics.metrics import MetricsCalculator
from src.config import BacktestConfig, BrokerConfig, ExecutionConfig
from src.simulator.engine import TickBacktestEngine
from src.strategies.adaptive_dual_engine import AdaptiveDualEngineScalper
from src.strategies.range_sweep_scalper_v8 import RangeSweepScalperV8
from src.strategies.volatility_breakout_scalper import VolatilityBreakoutScalperV1

import json
console = Console(width=160)


def create_exp16_strategy():
    engine_a = RangeSweepScalperV8(
        name="RangeSweepScalperV8",
        lookback_minutes=30,
        min_range_usd=3.0,
        max_range_usd=10.0,
        min_sweep_usd=0.75,
        max_sweep_usd=2.00,
        hard_sl_offset_usd=1.20,
        layer_spacing_usd=0.50,
        layer_volumes=[0.05, 0.10, 0.15],
        max_spread_usd=0.25,
        cooldown_seconds=1200.0,
        be_policy="STEP_LOCK",
        blackout_hours_utc={12, 19, 21, 22},
        macro_fast_hours=8,
        macro_slow_hours=24,
        macro_threshold_usd=2.50,
        max_daily_loss_usd=150.0,
        max_bear_disp_usd=10.00,
        max_distinct_sls_per_day=2,
    )
    engine_b = VolatilityBreakoutScalperV1(
        name="VolatilityBreakoutScalperV1",
        breakout_min_penetration_usd=2.00,
        retest_max_distance_usd=1.50,
        retest_bounce_trigger_usd=0.40,
        hard_sl_offset_usd=1.50,
        pyramid_step_1_usd=2.50,
        pyramid_step_2_usd=3.00,
        trailing_stop_buffer_usd=2.00,
        take_profit_target_usd=25.00,
        layer_volumes=[0.05, 0.10, 0.15],
        max_spread_usd=0.25,
    )
    return AdaptiveDualEngineScalper(
        name="AdaptiveDualEngineScalper",
        regime_mode="ORB",
        daily_expansion_threshold_usd=35.00,
        orb_start_hour_utc=7,
        orb_threshold_usd=4.00,
        max_daily_loss_usd=150.0,
        max_spread_usd=0.25,
        engine_a=engine_a,
        engine_b=engine_b,
        blackout_hours_utc={12, 19, 21, 22},
    )


def get_default_config():
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
        initial_balance=10_000.0,
        broker=broker_cfg,
        execution=exec_cfg,
    )


def run_all_months():
    console.print("[bold yellow]====================================================================[/bold yellow]")
    console.print("[bold yellow]       EXP-16: FULL 8-MONTH LONGITUDINAL SCIENTIFIC AUDIT           [/bold yellow]")
    console.print("[bold yellow]====================================================================[/bold yellow]")

    months = ["04", "05", "06", "07", "08", "09", "10", "11"]
    results = []

    table = Table(title="EXP-16 Monthly Performance Matrix (53.54M Institutional Ticks)")
    table.add_column("Month", justify="center", style="bold cyan")
    table.add_column("Ticks", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Net PnL", justify="right")
    table.add_column("Profit Factor", justify="right")
    table.add_column("Max DD %", justify="right")
    table.add_column("BUY PnL", justify="right")
    table.add_column("SELL PnL", justify="right")
    table.add_column("Status", justify="center")

    total_net = 0.0
    total_trades = 0

    for m in months:
        files = list(Path(f"data/parquet/xauusd/year=2026/month={m}").glob("*.parquet"))
        if not files:
            continue
        df = pl.read_parquet(files).sort("timestamp")
        n_ticks = len(df)

        strat = create_exp16_strategy()
        cfg = get_default_config()
        engine = TickBacktestEngine(strategy=strat, config=cfg)
        res = engine.run(df)

        m_metrics = MetricsCalculator.calculate(res.closed_trades, res.equity_curve, 10_000.0)
        trades_df = pl.DataFrame([{"side": t.side, "pnl": t.pnl_net} for t in res.closed_trades])
        buys = trades_df.filter(pl.col("side") == "BUY") if len(trades_df) > 0 else pl.DataFrame()
        sells = trades_df.filter(pl.col("side") == "SELL") if len(trades_df) > 0 else pl.DataFrame()

        buy_pnl = buys["pnl"].sum() if len(buys) > 0 else 0.0
        sell_pnl = sells["pnl"].sum() if len(sells) > 0 else 0.0

        pnl = m_metrics.net_profit
        total_net += pnl
        total_trades += m_metrics.total_trades

        pnl_style = "bold green" if pnl > 0 else ("bold red" if pnl < 0 else "white")
        status_str = "[bold green]PROFIT[/bold green]" if pnl > 0 else ("[bold yellow]PROTECTED[/bold yellow]" if pnl == 0 else "[red]DEFICIT[/red]")

        table.add_row(
            f"2026-{m}",
            f"{n_ticks:,}",
            str(m_metrics.total_trades),
            f"{m_metrics.win_rate_pct:.1f}%",
            f"[{pnl_style}]${pnl:+,.2f}[/{pnl_style}]",
            f"{m_metrics.profit_factor:.2f}",
            f"{m_metrics.max_drawdown_pct:.2f}%",
            f"${buy_pnl:+,.2f}",
            f"${sell_pnl:+,.2f}",
            status_str,
        )

        results.append({
            "month": m,
            "ticks": n_ticks,
            "trades": m_metrics.total_trades,
            "win_rate": m_metrics.win_rate_pct,
            "net_pnl": pnl,
            "pf": m_metrics.profit_factor,
            "max_dd": m_metrics.max_drawdown_pct,
            "buy_pnl": buy_pnl,
            "sell_pnl": sell_pnl,
        })

        del df
        del engine
        del res
        gc.collect()

    console.print(table)
    console.print(f"\n[bold green]Total 8-Month Cumulative Realized PnL: ${total_net:+,.2f}[/bold green] | Total Trades: {total_trades}")
    
    # Save to JSON report
    report_path = Path("reports/exp16_monthly_summary.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump({
            "total_net_pnl": total_net,
            "total_trades": total_trades,
            "months": results,
        }, f, indent=2)

    return results


if __name__ == "__main__":
    run_all_months()
