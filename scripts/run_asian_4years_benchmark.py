"""Standalone 4-Year Benchmark for Asian Close Breakout / Sweep Scalper.

Evaluates 49 continuous calendar months (November 2022 - November 2026)
on Exness institutional data with continuous monthly equity carryover,
dynamic HTF risk scaling (EMA50 vs EMA200), spread, and realistic execution.
"""

import argparse
import calendar
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import sys
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import MetaTrader5 as mt5
import numpy as np
import polars as pl
from rich.console import Console
from rich.table import Table

console = Console(width=160)

CACHE_DIR = Path("data/cache_bars")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MONTH_NAMES_ID = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
    9: "September", 10: "Oktober", 11: "November", 12: "Desember",
}


def fetch_and_cache_4years_data(terminal_path: str):
    """Ensure all 49 months (2022-11 to 2026-11) of M15 and H1 data are cached."""
    if not mt5.initialize(terminal_path):
        console.print(f"[red]Failed to initialize MT5: {mt5.last_error()}[/red]")
        sys.exit(1)

    sym = "XAUUSDm"
    mt5.symbol_select(sym, True)

    target_months = []
    # 2022: 11, 12
    for m in [11, 12]:
        target_months.append((2022, m))
    # 2023: 1..12
    for m in range(1, 13):
        target_months.append((2023, m))
    # 2024: 1..12
    for m in range(1, 13):
        target_months.append((2024, m))
    # 2025: 1..12
    for m in range(1, 13):
        target_months.append((2025, m))
    # 2026: 1..11
    for m in range(1, 12):
        target_months.append((2026, m))

    console.print(f"[cyan]Verifying / Caching data for {len(target_months)} months (2022-11 to 2026-11)...[/cyan]")

    for y, m in target_months:
        f_m15 = CACHE_DIR / f"m15_{y}_{m:02d}.parquet"
        f_h1 = CACHE_DIR / f"h1_{y}_{m:02d}.parquet"

        if f_m15.exists() and f_h1.exists() and not (y == 2026 and m == 11):
            continue

        last_day = calendar.monthrange(y, m)[1]
        if y == 2026 and m == 11:
            last_day = 13  # today

        s = datetime(y, m, 1, 0, 0, tzinfo=timezone.utc)
        e = datetime(y, m, last_day, 23, 59, 59, tzinfo=timezone.utc)

        rates_m15 = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M15, s, e)
        if rates_m15 is not None and len(rates_m15) > 0:
            df_m15 = pl.from_numpy(rates_m15).with_columns(
                pl.from_epoch(pl.col("time"), time_unit="s").alias("timestamp")
            )
            df_m15.write_parquet(f_m15)

        rates_h1 = mt5.copy_rates_range(sym, mt5.TIMEFRAME_H1, s, e)
        if rates_h1 is not None and len(rates_h1) > 0:
            df_h1 = pl.from_numpy(rates_h1).with_columns(
                pl.from_epoch(pl.col("time"), time_unit="s").alias("timestamp")
            )
            df_h1.write_parquet(f_h1)

        console.print(f"[green]Cached {y}-{m:02d}: M15={len(rates_m15) if rates_m15 is not None else 0:,} bars, H1={len(rates_h1) if rates_h1 is not None else 0:,} bars[/green]")

    mt5.shutdown()


class Asian4YearsSimulator:
    """High-precision Asian Breakout simulator with causal EMA50/200 HTF risk scaling."""

    def __init__(
        self,
        buffer_usd: float = 1.0,
        sl_range_mult: float = 0.50,
        tp_range_mult: Optional[float] = None,  # None = NO-TP Session Close Exit
        aligned_risk_pct: float = 0.0125,
        counter_risk_pct: float = 0.0035,
        min_asian_range: float = 5.0,
        max_asian_range: float = 120.0,
        spread_usd: float = 0.16,
        slippage_usd: float = 0.02,
        session_close_hour: int = 20,
        session_close_min: int = 55,
    ):
        self.buffer_usd = buffer_usd
        self.sl_range_mult = sl_range_mult
        self.tp_range_mult = tp_range_mult
        self.aligned_risk_pct = aligned_risk_pct
        self.counter_risk_pct = counter_risk_pct
        self.min_asian_range = min_asian_range
        self.max_asian_range = max_asian_range
        self.spread_usd = spread_usd
        self.slippage_usd = slippage_usd
        self.session_close_hour = session_close_hour
        self.session_close_min = session_close_min

        # Causal EMA state
        self.ema50: Optional[float] = None
        self.ema200: Optional[float] = None
        self.h1_bars_count: int = 0

    def update_h1_ema(self, h1_close: float):
        """Update causal H1 EMA50 and EMA200 without lookahead bias."""
        a50 = 2.0 / 51.0
        a200 = 2.0 / 201.0
        self.ema50 = h1_close if self.ema50 is None else (a50 * h1_close + (1.0 - a50) * self.ema50)
        self.ema200 = h1_close if self.ema200 is None else (a200 * h1_close + (1.0 - a200) * self.ema200)
        self.h1_bars_count += 1

    def run_month(
        self,
        year: int,
        month: int,
        start_balance: float,
    ) -> dict:
        f_m15 = CACHE_DIR / f"m15_{year}_{month:02d}.parquet"
        f_h1 = CACHE_DIR / f"h1_{year}_{month:02d}.parquet"

        if not f_m15.exists() or not f_h1.exists():
            return {"status": "SKIPPED", "start_balance": start_balance, "end_balance": start_balance, "net_pnl": 0.0}

        df_m15 = pl.read_parquet(f_m15).sort("timestamp")
        df_h1 = pl.read_parquet(f_h1).sort("timestamp")

        h1_records = {row["timestamp"]: row["close"] for row in df_h1.to_dicts()}

        current_balance = start_balance
        equity_peak = start_balance
        max_drawdown_pct = 0.0
        trades = []

        bars = df_m15.to_dicts()

        days_map: dict[date, list[dict]] = {}
        for b in bars:
            ts: datetime = b["timestamp"]
            if ts.minute == 0 and ts in h1_records:
                self.update_h1_ema(h1_records[ts])

            t_day = (ts + timedelta(hours=1)).date() if ts.hour >= 23 else ts.date()
            if t_day not in days_map:
                days_map[t_day] = []
            days_map[t_day].append(b)

        for t_day in sorted(days_map.keys()):
            day_bars = days_map[t_day]

            # 1. Asian Session (23:00 - 06:59 UTC)
            asian_bars = [b for b in day_bars if b["timestamp"].hour in {23, 0, 1, 2, 3, 4, 5, 6}]
            if not asian_bars:
                continue

            asian_high = max(b["high"] for b in asian_bars)
            asian_low = min(b["low"] for b in asian_bars)
            asian_range = asian_high - asian_low

            if not (self.min_asian_range <= asian_range <= self.max_asian_range):
                continue

            # 2. Entry Window (07:00 - 15:59 UTC)
            entry_bars = [b for b in day_bars if 7 <= b["timestamp"].hour < 16]
            open_pos = None

            buy_trigger = asian_high + self.buffer_usd
            sell_trigger = asian_low - self.buffer_usd
            sl_dist = self.sl_range_mult * asian_range
            tp_dist = self.tp_range_mult * asian_range if self.tp_range_mult is not None else None

            for b in entry_bars:
                ts: datetime = b["timestamp"]
                is_bull = (self.ema50 > self.ema200) if (self.ema50 is not None and self.ema200 is not None and self.h1_bars_count >= 50) else True

                # BUY breakout
                if b["high"] >= buy_trigger:
                    aligned = is_bull
                    risk_pct = self.aligned_risk_pct if aligned else self.counter_risk_pct
                    risk_usd = current_balance * risk_pct
                    raw_lot = risk_usd / (sl_dist * 100.0)
                    lots = max(0.01, min(5.00, round(raw_lot, 2)))

                    entry_price = buy_trigger + self.slippage_usd
                    sl_price = entry_price - sl_dist
                    tp_price = entry_price + tp_dist if tp_dist is not None else None

                    open_pos = {
                        "side": "BUY",
                        "lots": lots,
                        "entry_time": ts,
                        "entry_price": entry_price,
                        "sl": sl_price,
                        "tp": tp_price,
                        "aligned": aligned,
                        "entry_bar_idx": day_bars.index(b),
                    }
                    break

                # SELL breakout
                elif b["low"] <= sell_trigger:
                    aligned = not is_bull
                    risk_pct = self.aligned_risk_pct if aligned else self.counter_risk_pct
                    risk_usd = current_balance * risk_pct
                    raw_lot = risk_usd / (sl_dist * 100.0)
                    lots = max(0.01, min(5.00, round(raw_lot, 2)))

                    entry_price = sell_trigger - self.slippage_usd
                    sl_price = entry_price + sl_dist
                    tp_price = entry_price - tp_dist if tp_dist is not None else None

                    open_pos = {
                        "side": "SELL",
                        "lots": lots,
                        "entry_time": ts,
                        "entry_price": entry_price,
                        "sl": sl_price,
                        "tp": tp_price,
                        "aligned": aligned,
                        "entry_bar_idx": day_bars.index(b),
                    }
                    break

            if open_pos is None:
                continue

            # 3. Simulate trade exit
            entry_idx = open_pos["entry_bar_idx"]
            subsequent_bars = day_bars[entry_idx:]
            closed_trade = None

            for b in subsequent_bars:
                ts: datetime = b["timestamp"]

                if open_pos["side"] == "BUY":
                    if b["low"] <= open_pos["sl"]:
                        exit_price = open_pos["sl"] - self.slippage_usd
                        gross_pnl = (exit_price - open_pos["entry_price"]) * open_pos["lots"] * 100.0
                        net_pnl = gross_pnl - (self.spread_usd * open_pos["lots"] * 100.0)
                        closed_trade = {**open_pos, "exit_time": ts, "exit_price": exit_price, "exit_reason": "SL", "pnl": net_pnl}
                        break
                    if open_pos["tp"] is not None and b["high"] >= open_pos["tp"]:
                        exit_price = open_pos["tp"]
                        gross_pnl = (exit_price - open_pos["entry_price"]) * open_pos["lots"] * 100.0
                        net_pnl = gross_pnl - (self.spread_usd * open_pos["lots"] * 100.0)
                        closed_trade = {**open_pos, "exit_time": ts, "exit_price": exit_price, "exit_reason": "TP", "pnl": net_pnl}
                        break
                    if ts.hour == self.session_close_hour and ts.minute >= 45:
                        exit_price = b["close"] - self.slippage_usd
                        gross_pnl = (exit_price - open_pos["entry_price"]) * open_pos["lots"] * 100.0
                        net_pnl = gross_pnl - (self.spread_usd * open_pos["lots"] * 100.0)
                        closed_trade = {**open_pos, "exit_time": ts, "exit_price": exit_price, "exit_reason": "SESSION_CLOSE", "pnl": net_pnl}
                        break

                elif open_pos["side"] == "SELL":
                    if b["high"] >= open_pos["sl"]:
                        exit_price = open_pos["sl"] + self.slippage_usd
                        gross_pnl = (open_pos["entry_price"] - exit_price) * open_pos["lots"] * 100.0
                        net_pnl = gross_pnl - (self.spread_usd * open_pos["lots"] * 100.0)
                        closed_trade = {**open_pos, "exit_time": ts, "exit_price": exit_price, "exit_reason": "SL", "pnl": net_pnl}
                        break
                    if open_pos["tp"] is not None and b["low"] <= open_pos["tp"]:
                        exit_price = open_pos["tp"]
                        gross_pnl = (open_pos["entry_price"] - exit_price) * open_pos["lots"] * 100.0
                        net_pnl = gross_pnl - (self.spread_usd * open_pos["lots"] * 100.0)
                        closed_trade = {**open_pos, "exit_time": ts, "exit_price": exit_price, "exit_reason": "TP", "pnl": net_pnl}
                        break
                    if ts.hour == self.session_close_hour and ts.minute >= 45:
                        exit_price = b["close"] + self.slippage_usd
                        gross_pnl = (open_pos["entry_price"] - exit_price) * open_pos["lots"] * 100.0
                        net_pnl = gross_pnl - (self.spread_usd * open_pos["lots"] * 100.0)
                        closed_trade = {**open_pos, "exit_time": ts, "exit_price": exit_price, "exit_reason": "SESSION_CLOSE", "pnl": net_pnl}
                        break

            if closed_trade is None and open_pos is not None:
                last_b = subsequent_bars[-1]
                if open_pos["side"] == "BUY":
                    exit_price = last_b["close"] - self.slippage_usd
                    gross_pnl = (exit_price - open_pos["entry_price"]) * open_pos["lots"] * 100.0
                else:
                    exit_price = last_b["close"] + self.slippage_usd
                    gross_pnl = (open_pos["entry_price"] - exit_price) * open_pos["lots"] * 100.0
                net_pnl = gross_pnl - (self.spread_usd * open_pos["lots"] * 100.0)
                closed_trade = {**open_pos, "exit_time": last_b["timestamp"], "exit_price": exit_price, "exit_reason": "EOD_FORCE", "pnl": net_pnl}

            if closed_trade is not None:
                current_balance += closed_trade["pnl"]
                if current_balance > equity_peak:
                    equity_peak = current_balance
                dd_pct = ((equity_peak - current_balance) / equity_peak) * 100.0 if equity_peak > 0 else 0.0
                if dd_pct > max_drawdown_pct:
                    max_drawdown_pct = dd_pct
                trades.append(closed_trade)

        net_pnl = current_balance - start_balance
        ret_pct = (net_pnl / start_balance) * 100.0 if start_balance > 0 else 0.0
        total_trades = len(trades)
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] < 0]
        win_rate = (len(wins) / total_trades) * 100.0 if total_trades > 0 else 0.0
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        pf = (gross_profit / gross_loss) if gross_loss > 0 else (99.9 if gross_profit > 0 else 0.0)

        buys = [t for t in trades if t["side"] == "BUY"]
        sells = [t for t in trades if t["side"] == "SELL"]
        buy_pnl = sum(t["pnl"] for t in buys)
        sell_pnl = sum(t["pnl"] for t in sells)

        status = "PROFIT" if net_pnl > 0 else ("PROTECTED" if abs(ret_pct) <= 0.6 else "DEFICIT")

        return {
            "year": year,
            "month": month,
            "month_name": f"{MONTH_NAMES_ID.get(month, f'Month {month}')} {year}",
            "start_balance": start_balance,
            "net_pnl": net_pnl,
            "end_balance": current_balance,
            "return_pct": ret_pct,
            "max_dd_pct": max_drawdown_pct,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": pf,
            "buy_count": len(buys),
            "buy_pnl": buy_pnl,
            "sell_count": len(sells),
            "sell_pnl": sell_pnl,
            "status": status,
            "trades": trades,
        }


def run_4year_benchmark(fixed_tp: bool = False, tp_mult: float = 1.0, min_range: float = 16.0):
    mode_name = f"Fixed TP = {tp_mult:.2f}R" if fixed_tp else "NO-TP (Session Close 20:55 UTC)"
    console.print(f"\n[bold cyan]========================================================================================[/bold cyan]")
    console.print(f"[bold cyan]  STANDALONE 4-YEAR ASIAN BREAKOUT / SWEEP BENCHMARK (NOV 2022 - NOV 2026)             [/bold cyan]")
    console.print(f"[bold cyan]  Mode: {mode_name} | MinRange=${min_range:.1f} | SL=0.50R (Asian EQ) | RiskScale (1.25%/0.35%) [/bold cyan]")
    console.print(f"[bold cyan]========================================================================================[/bold cyan]\n")

    sim = Asian4YearsSimulator(
        buffer_usd=1.0,
        sl_range_mult=0.50,
        tp_range_mult=tp_mult if fixed_tp else None,
        aligned_risk_pct=0.0125,
        counter_risk_pct=0.0035,
        min_asian_range=min_range,
        max_asian_range=120.0,
        spread_usd=0.16,
        slippage_usd=0.02,
        session_close_hour=20,
        session_close_min=55,
    )


    months_to_run = []
    for m in [11, 12]:
        months_to_run.append((2022, m))
    for m in range(1, 13):
        months_to_run.append((2023, m))
    for m in range(1, 13):
        months_to_run.append((2024, m))
    for m in range(1, 13):
        months_to_run.append((2025, m))
    for m in range(1, 12):
        months_to_run.append((2026, m))

    current_balance = 10_000.0
    overall_peak = 10_000.0
    max_cum_dd_pct = 0.0
    records = []
    all_trades = []

    for y, m in months_to_run:
        res = sim.run_month(y, m, current_balance)
        if res["status"] == "SKIPPED":
            continue

        records.append(res)
        all_trades.extend(res["trades"])

        if res["end_balance"] > overall_peak:
            overall_peak = res["end_balance"]
        dd_now = ((overall_peak - res["end_balance"]) / overall_peak) * 100.0 if overall_peak > 0 else 0.0
        if dd_now > max_cum_dd_pct:
            max_cum_dd_pct = dd_now

        current_balance = res["end_balance"]

        status_color = "green" if res["net_pnl"] > 0 else ("yellow" if res["status"] == "PROTECTED" else "red")
        console.print(
            f"[{status_color}]{res['month_name']:<18} | PnL: ${res['net_pnl']:>+9.2f} ({res['return_pct']:>+6.2f}%) | "
            f"End: ${res['end_balance']:>10.2f} | DD: {res['max_dd_pct']:>5.2f}% | "
            f"Trades: {res['total_trades']:>2} | WR: {res['win_rate']:>5.1f}% | PF: {res['profit_factor']:>5.2f} | {res['status']}[/{status_color}]"
        )

    table = Table(title=f"Continuous 49-Month Equity Carryover: Standalone Asian Breakout ({mode_name})")
    cols = ["Bulan Kalender", "Modal Awal ($)", "Net PnL ($)", "Modal Akhir ($)", "Return (%)", "Max DD (%)", "Trades", "Win Rate (%)", "PF", "BUY (N/$)", "SELL (N/$)", "Status"]
    for c in cols:
        table.add_column(c, justify="right" if c not in ("Bulan Kalender", "Status") else "left")

    for r in records:
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

    console.print("\n")
    console.print(table)

    tot_net = current_balance - 10_000.0
    tot_ret = (tot_net / 10_000.0) * 100.0
    pos_months = sum(1 for r in records if r["net_pnl"] > 0)
    prot_months = sum(1 for r in records if r["status"] == "PROTECTED")
    loss_months = sum(1 for r in records if r["status"] == "DEFICIT")

    console.print(f"\n[bold]=== HASIL AKHIR PENGUJIAN 4 TAHUN (49 BULAN) ===[/bold]")
    console.print(f"Modal Awal Portofolio (1 Nov 2022):  $10,000.00")
    console.print(f"Modal Akhir Portofolio (13 Nov 2026): [bold green]${current_balance:,.2f}[/bold green]")
    console.print(f"Total Net Profit Kumulatif 4 Tahun:  [bold green]${tot_net:+,.2f} ({tot_ret:+.2f}%)[/bold green]")
    console.print(f"Max Drawdown Terbesar Melintasi 4 Tahun: [bold yellow]{max_cum_dd_pct:.2f}%[/bold yellow]")
    console.print(f"Konsistensi Bulanan: {pos_months} PROFIT / {prot_months} PROTECTED / {loss_months} DEFICIT (Total {len(records)} Bulan)")
    console.print(f"Total Transaksi 4 Tahun: {len(all_trades)} trades\n")

    return records, all_trades, current_balance, tot_net, tot_ret, max_cum_dd_pct


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal-path", type=str, default=r"C:\MetaTrader 5 - RESEARCH - EA\terminal64.exe")
    parser.add_argument("--fixed-tp", action="store_true", help="Use Fixed TP mode instead of Session Close")
    parser.add_argument("--tp-mult", type=float, default=1.0, help="TP multiplier if fixed-tp is true")
    parser.add_argument("--min-range", type=float, default=16.0, help="Minimum Asian Range in USD (default: 16.0)")
    args = parser.parse_args()

    fetch_and_cache_4years_data(args.terminal_path)
    run_4year_benchmark(fixed_tp=args.fixed_tp, tp_mult=args.tp_mult, min_range=args.min_range)

