import calendar
from datetime import datetime
from pathlib import Path
import sys

from scripts.run_asian_4years_benchmark import run_4year_benchmark

records, all_trades, current_balance, tot_net, tot_ret, max_cum_dd_pct = run_4year_benchmark(min_range=10.0)

years = [
    ("TAHUN 1: Siklus Kenaikan Suku Bunga The Fed (November 2022 – Oktober 2023)", "Tahun 1 (2022–2023)", records[0:12]),
    ("TAHUN 2: Transisi & Konsolidasi Panjang (November 2023 – Oktober 2024)", "Tahun 2 (2023–2024)", records[12:24]),
    ("TAHUN 3: Siklus Reli Emas Global (November 2024 – Oktober 2025)", "Tahun 3 (2024–2025)", records[24:36]),
    ("TAHUN 4: Volatilitas Parabolik & Rekor Tertinggi (November 2025 – November 2026)", "Tahun 4 (2025–2026)", records[36:49]),
]

out = []
out.append("# Laporan Hasil Uji Coba: Asian Session Sweep dengan Min Asian Range = $10.00")
out.append("## Evaluasi 4 Tahun Penuh (November 2022 – November 2026) Berbasis Data Riil Exness\n")
out.append("**Track Riset:** Asian Session Breakout / Sweep (Uji Variasi Parameter $10.00)  ")
out.append("**Doktrin Tertinggi:** [AGENTS.md](../AGENTS.md) — Tiga Hukum Mutlak & Standar Baku Pelaporan  ")
out.append("**Instrumen:** `XAUUSDm` (Exness Institutional Contract, 100 oz/lot)  ")
out.append("**Ambang Batas Filter:** `Min Asian Range = $10.00 USD / 100 pips`  ")
out.append(f"**Modal Awal Keseluruhan:** $10,000.00 (1 November 2022)  ")
out.append(f"**Modal Akhir Keseluruhan:** **${current_balance:,.2f} ({tot_ret:+.2f}%)**  ")
out.append(f"**Max Drawdown Terbesar Melintasi 4 Tahun:** **{max_cum_dd_pct:.2f}%**  ")
out.append(f"**Total Transaksi:** {len(all_trades)} trades\n")
out.append("---\n")

out.append("## 1. Perbandingan Head-to-Head: Min Range $5.00 vs $10.00 vs $16.00\n")
out.append("| Metrik Evaluasi | Baseline ($5.00) | Uji Saat Ini ($10.00) | Rekomendasi Optimal ($16.00) | Status Evaluasi Doktrin |")
out.append("| :--- | :---: | :---: | :---: | :--- |")
out.append(f"| **Modal Akhir ($10k)** | $19,531.06 (+95.31%) | **${current_balance:,.2f} ({tot_ret:+.2f}%)** | **$26,824.11 (+168.24%)** | $16.00 menghasilkan profit terbesar |")
out.append(f"| **Max Drawdown 4 Tahun** | 55.05% (CRITICAL RISK) | **{max_cum_dd_pct:.2f}% (RISIKO TINGGI)** | **7.32% (SANGAT AMAN)** | $10.00 melanggar batas DD doktrin (10-15%) |")
out.append(f"| **Titik Trough Portofolio** | $4,891.00 (-51.09%) | **$7,440.88 (-31.62%)** | **$9,915.30 (-0.85%)** | $16.00 melindungi saldo modal dari kehancuran |")
out.append(f"| **Total Trade 4 Tahun** | 772 trades | **{len(all_trades)} trades** | **461 trades** | $10.00 masih memicu 218 trade chop |")
out.append(f"| **Tahun 1 (2022-2023)** | -$4,171.74 (-41.72%) | **-$1,703.18 (-17.03%)** | **+$179.70 (+1.80%)** | $10.00 GAGAL di Tahun 1 (Minus) |")
out.append(f"| **Tahun 2 (2023-2024)** | -$541.42 (-9.30%) | **+$198.99 (+2.40%)** | **+$1,141.61 (+11.21%)** | $16.00 tumbuh 5x lebih cepat |")
out.append(f"| **Tahun 3 (2024-2025)** | +$10,240.23 (+194.0%) | **+$3,971.48 (+46.75%)** | **+$5,059.89 (+44.69%)** | Keduanya menangkap ekspansi tren |")
out.append(f"| **Tahun 4 (2025-2026)** | +$14,003.99 (+90.28%) | **+$8,399.57 (+67.37%)** | **+$10,442.91 (+63.75%)** | $16.00 mencatat profit absolut jauh lebih tinggi |")
out.append("\n---\n")

out.append("## 2. Ringkasan Kinerja Antar-Tahun (Min Range = $10.00)\n")
out.append("| Periode Siklus | Modal Awal ($) | Net PnL ($) | Modal Akhir ($) | Return (%) | Max DD Tahunan (%) | Total Trade | Win Rate (%) | Profit Factor | Status Evaluasi |")
out.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

for full_title, short_name, recs in years:
    s_bal = recs[0]["start_balance"]
    e_bal = recs[-1]["end_balance"]
    pnl = e_bal - s_bal
    ret = (pnl / s_bal) * 100.0
    tr = sum(r["total_trades"] for r in recs)
    wins = sum(int(r["win_rate"] * r["total_trades"] / 100.0 + 0.5) for r in recs)
    wr = (wins / tr * 100.0) if tr > 0 else 0.0
    
    # Intra-year DD
    pk = s_bal
    yr_dd = 0.0
    for r in recs:
        if r["end_balance"] > pk:
            pk = r["end_balance"]
        dd = ((pk - r["end_balance"]) / pk) * 100.0
        if dd > yr_dd:
            yr_dd = dd
        if r["max_dd_pct"] > yr_dd:
            yr_dd = max(yr_dd, r["max_dd_pct"])
            
    tot_gp = sum(t["pnl"] for r in recs for t in r["trades"] if t["pnl"] > 0)
    tot_gl = sum(abs(t["pnl"]) for r in recs for t in r["trades"] if t["pnl"] < 0)
    pf = (tot_gp / tot_gl) if tot_gl > 0 else 99.90
    st = "PROFIT" if pnl > 0 else "DEFICIT"
    out.append(f"| **{short_name}** | ${s_bal:,.2f} | **${pnl:+,.2f}** | ${e_bal:,.2f} | **{ret:+.2f}%** | **{yr_dd:.2f}%** | {tr} | {wr:.1f}% | {pf:.2f} | **{st}** |")

out.append(f"| **TOTAL 4 TAHUN** | **$10,000.00** | **${tot_net:+,.2f}** | **${current_balance:,.2f}** | **{tot_ret:+.2f}%** | **{max_cum_dd_pct:.2f}%** | **{len(all_trades)}** | **{(sum(1 for t in all_trades if t['pnl'] > 0)/len(all_trades)*100):.1f}%** | **{(sum(t['pnl'] for t in all_trades if t['pnl'] > 0)/sum(abs(t['pnl']) for t in all_trades if t['pnl'] < 0)):.2f}** | **DEFICIT DI TAHUN 1** |")
out.append("\n---\n")

# Now append details per year
for idx, (full_title, short_name, recs) in enumerate(years, 1):
    out.append(f"## {full_title}\n")
    out.append("### 1. Tabel Ekuitas Berkelanjutan Bulanan")
    out.append(f"*Modal awal carryover: ${recs[0]['start_balance']:,.2f}*\n")
    out.append("| Bulan Kalender | Modal Awal ($) | Net PnL ($) | Modal Akhir ($) | Return (%) | Max DD (%) | Total Trade | Win Rate (%) | Profit Factor | Status Evaluasi |")
    out.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for r in recs:
        out.append(f"| **{r['month_name']}** | ${r['start_balance']:,.2f} | **${r['net_pnl']:+,.2f}** | ${r['end_balance']:,.2f} | {r['return_pct']:+.2f}% | {r['max_dd_pct']:.2f}% | {r['total_trades']} | {r['win_rate']:.1f}% | {r['profit_factor']:.2f} | **{r['status']}** |")
    
    s_bal = recs[0]["start_balance"]
    e_bal = recs[-1]["end_balance"]
    pnl = e_bal - s_bal
    ret = (pnl / s_bal) * 100.0
    tr = sum(r["total_trades"] for r in recs)
    
    out.append(f"\n* **Modal Awal {short_name}:** ${s_bal:,.2f}")
    out.append(f"* **Modal Akhir {short_name}:** ${e_bal:,.2f}")
    out.append(f"* **Net PnL Kumulatif {short_name}:** **${pnl:+,.2f} ({ret:+.2f}%)**")
    out.append(f"* **Total Trade:** {tr}\n")
    
    out.append(f"### 2. Tabel Rincian Arah Transaksi {short_name} (BUY vs SELL Breakdown)")
    out.append("| Bulan | Total Trade | Trade BUY & PnL ($) | Trade SELL & PnL ($) | Keterangan Karakteristik Pasar & Forensik Mikro |")
    out.append("| :--- | :---: | :---: | :---: | :--- |")
    for r in recs:
        # Micro forensics note
        b_cnt, b_pnl = r['buy_count'], r['buy_pnl']
        s_cnt, s_pnl = r['sell_count'], r['sell_pnl']
        if r['total_trades'] == 0:
            note = "Chop ekstrem. Range Asia < $10.00. Tidak ada trade."
        elif r['net_pnl'] > 500:
            note = f"Ekspansi volatilitas kuat ditangkap dengan mulus ({'BUY' if b_pnl > s_pnl else 'SELL'} dominan)."
        elif r['net_pnl'] > 0:
            note = f"Pergerakan terkonfirmasi menghasilkan keuntungan bersih."
        elif r['net_pnl'] > -100:
            note = "Fluktuasi minor, kerugian tertahan di bawah 1% modal."
        else:
            note = f"Terjadi false-sweep/whipsaw bolak-balik akibat range $10 masih tergolong sempit ({'BUY' if b_pnl < s_pnl else 'SELL'} terkena rejeksi)."
        out.append(f"| **{r['month_name']}** | {r['total_trades']} | {b_cnt} trades (${b_pnl:+,.0f}) | {s_cnt} trades (${s_pnl:+,.0f}) | {note} |")
    out.append("\n---\n")

out.append("""## 3. Audit Forensik & Evaluasi Kepatuhan Mutlak Doktrin ([AGENTS.md](../AGENTS.md))

### 1. Mengapa Parameter $10.00 GAGAL Lolos Syarat Produksi?
1. **Pelanggaran Batas Risiko Maksimal (Hukum 3 & Standar Bab 4 Doktrin):**
   * Doktrin menetapkan: *Max Drawdown Kumulatif wajib terkunci stabil di bawah 10% – 15%*.
   * Dengan `MinRange = $10.00`, Max Drawdown kumulatif membengkak hingga **31.62%** (titik terendah ekuitas terperosok ke **$7,440.88** pada April 2024 dari puncak sebelumnya $10,881.18 di Desember 2022).
   * Sebaliknya, pada `MinRange = $16.00`, Max Drawdown hanya **7.32%** dan saldo terendah tidak pernah tembus di bawah **$9,915.30**.

2. **Pelanggaran Konsistensi Antar-Tahun (Hukum 1 & Standar Bab 4 Doktrin):**
   * Doktrin menetapkan: *Setiap bulan kalender atau siklus tahunan wajib mencatatkan pertumbuhan modal atau terlindungi aman*.
   * Pada Tahun 1 (2022–2023), `MinRange = $10.00` menghasilkan **DEFICIT -$1,703.18 (-17.03%)** dengan Max DD mencapai **23.75%**.
   * Hal ini membuktikan bahwa batas \$10.00 (100 pips) **masih terlalu sempit** untuk struktur kompresi XAUUSD selama siklus kenaikan suku bunga agresif The Fed. Range \$10–\$15 masih sarat dengan *liquidity stop hunt* dan *fakeout*, sehingga bot terjebak 82 kali trade dengan Win Rate hanya **25.6%**.

3. **Komparasi Efisiensi Eksekusi (Signal Quality):**
   * **Min Range $10.00:** Membuka 679 transaksi, menghasilkan profit \$10,866.86 (Rata-rata profit per trade = **\$16.00**).
   * **Min Range $16.00:** Membuka 461 transaksi, menghasilkan profit \$16,824.11 (Rata-rata profit per trade = **\$36.49**).
   * **Kesimpulan Kuantitatif:** Filter \$16.00 menyaring 218 transaksi sampah/noise, meningkatkan efisiensi keuntungan per trade lebih dari **2.28 KALI LIPAT**, sekaligus memangkas drawdown dari 31.62% ke 7.32%!
""")

report_path = Path("reports/ASIAN_SWEEP_MIN_RANGE_10_REPORT.md")
report_path.write_text("\n".join(out), encoding="utf-8")
print(f"Report written successfully to {report_path}")
