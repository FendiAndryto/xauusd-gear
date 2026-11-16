import sys
from pathlib import Path
from scripts.run_asian_4years_benchmark import run_4year_benchmark

records, all_trades, current_balance, tot_net, tot_ret, max_cum_dd_pct = run_4year_benchmark(min_range=10.0)

years = [
    ("Tahun 1 (2022–2023)", records[0:12]),
    ("Tahun 2 (2023–2024)", records[12:24]),
    ("Tahun 3 (2024–2025)", records[24:36]),
    ("Tahun 4 (2025–2026)", records[36:49]),
]

print("\n" + "="*80)
print("ANNUAL SUMMARY TABLE (MIN RANGE = $10.00)")
print("="*80)
for name, recs in years:
    start_bal = recs[0]["start_balance"]
    end_bal = recs[-1]["end_balance"]
    pnl = end_bal - start_bal
    ret = (pnl / start_bal) * 100.0
    trades = sum(r["total_trades"] for r in recs)
    wins = sum(int(r["win_rate"] * r["total_trades"] / 100.0 + 0.5) for r in recs)
    wr = (wins / trades * 100.0) if trades > 0 else 0.0
    
    # Calculate peak-to-trough within the year
    peak = start_bal
    yr_max_dd = 0.0
    for r in recs:
        # Check intra-month DD relative to start/peak
        if r["end_balance"] > peak:
            peak = r["end_balance"]
        dd = ((peak - r["end_balance"]) / peak) * 100.0
        if dd > yr_max_dd:
            yr_max_dd = dd
        if r["max_dd_pct"] > yr_max_dd:
            yr_max_dd = max(yr_max_dd, r["max_dd_pct"])
            
    # Calculate Profit Factor for the year
    total_gross_profit = 0.0
    total_gross_loss = 0.0
    for r in recs:
        for t in r["trades"]:
            if t["pnl"] > 0:
                total_gross_profit += t["pnl"]
            else:
                total_gross_loss += abs(t["pnl"])
    pf = (total_gross_profit / total_gross_loss) if total_gross_loss > 0 else 99.90

    status = "PROFIT" if pnl > 0 else "DEFICIT"
    print(f"{name} | Modal Awal: ${start_bal:,.2f} | Net PnL: ${pnl:+,.2f} | Modal Akhir: ${end_bal:,.2f} | Return: {ret:+.2f}% | Max DD: {yr_max_dd:.2f}% | Trades: {trades} | WR: {wr:.1f}% | PF: {pf:.2f} | Status: {status}")

print("\n" + "="*80)
print("MONTHLY BREAKDOWN PER YEAR")
print("="*80)
for name, recs in years:
    print(f"\n--- {name} ---")
    for r in recs:
        print(f"{r['month_name']:<18} | Start: ${r['start_balance']:>10.2f} | PnL: ${r['net_pnl']:>+9.2f} ({r['return_pct']:>+6.2f}%) | End: ${r['end_balance']:>10.2f} | DD: {r['max_dd_pct']:>5.2f}% | Trades: {r['total_trades']:>2} | WR: {r['win_rate']:>5.1f}% | PF: {r['profit_factor']:>5.2f} | BUY: {r['buy_count']:>2} (${r['buy_pnl']:>+7.0f}) | SELL: {r['sell_count']:>2} (${r['sell_pnl']:>+7.0f}) | {r['status']}")
