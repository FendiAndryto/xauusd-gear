# Spesifikasi Teknis & Rencana Validasi: Fase O
## EXP-16: Multi-Horizon Structural Momentum Scalper (Market Structure Adaptation)

**Proyek:** XAUUSD Quantitative Scalping Research Platform  
**Fase:** Fase O (EXP-16: Multi-Horizon Structural Momentum Scalper)  
**Doktrin Tertinggi:** [AGENTS.md](../../AGENTS.md) — Tiga Hukum Mutlak Penelitian  
**Versi Dokumen:** 1.0.0  
**Tanggal:** 2026-11-08  
**Status Target:** Validasi Menyeluruh Melintasi 53.541.349 Tick Riil Exness (`XAUUSDm`, April – November 2026)  

---

## 1. Landasan Penelitian & Dekomposisi Masalah

Berdasarkan Piagam Hukum Tertinggi ([AGENTS.md](../../AGENTS.md)), penelitian robot trading kuantitatif XAUUSD berpegang teguh pada:
* **HUKUM 1:** Pertahankan Alpha yang Sudah Menang (Preserve the Winning Edge: Juli +\$2.477,79 dan November +\$1.056,69 pada baseline EXP-12).
* **HUKUM 2:** Adaptasi Struktur Pasar, BUKAN Pemotongan Kalender Statis (Market Structure Adaptation, Not Blind Time Pruning). Dilarang keras mematikan hari Senin atau memblokir jam trading secara arbitrer.
* **HUKUM 3:** Validasi Menyeluruh Melintasi Seluruh Bulan (Continuous Multi-Month Audit).

### Diagnosa Forensik Kegagalan Bulan Tertentu (Oktober 2026):
1. **Dekomposisi Arah BUY vs SELL:**
   * Di bulan Oktober (kerugian -\$1.293,47), **70,8% kerugian (-\$916,38)** disumbang oleh posisi **BUY** dengan Win Rate hanya **15,9%**.
   * Posisi SELL di bulan Oktober mencatatkan defisit -\$377,09, terkonsentrasi pada hari reli ekspansi naik (26 Oktober -\$217,48).
2. **Akar Masalah Struktur: *The Rolling Range Trap in Cascading Trends*:**
   * `RangeDetector` standar menggunakan jendela bergulir 30 menit dan hanya memverifikasi apakah `width` berada di antara \$3.00 – \$10.00.
   * Pada hari tren air terjun bertingkat (*cascading trend* seperti 12, 13, 14, dan 19 Oktober), harga emas jatuh \$30–\$40 dalam pola tangga (turun \$10, konsolidasi 15 menit, lalu turun lagi \$10).
   * Pada saat konsolidasi 15 menit, perbedaan MA 8-bar vs 25-bar hanya bernilai -\$0,82 (lebih kecil dari ambang batas statis \$1,20), sehingga detektor keliru mengklasifikasikan rezim pasar sebagai **`NEUTRAL`**.
   * Karena filter Wasit ORB London (07:00–08:00 UTC) belum aktif pada sesi Asia (00:00–07:00 UTC), robot mendeteksi penembusan batas bawah konsolidasi sementara sebagai *liquidity sweep* dan melakukan entri BUY berulang kali ke dalam pisau jatuh.

---

## 2. Inovasi Solusi: Multi-Horizon Structural Momentum Gate

Untuk mengatasi anomali di atas tanpa mengubah aturan kalender (Senin tetap ON, jam Asia tetap aktif):
1. **Deteksi Momentum Perpindahan Harga 45–60 Menit (`h1_displacement`):**
   * Detektor mengevaluasi perpindahan harga rolling 45–60 menit dari buffer 180 bar M1 dalam waktu streaming $O(1)$ setiap pergantian bar menit:
     $$\Delta P_{H1} = P_{\text{mid}}(t) - P_{\text{mid}}(t - 45\text{m})$$
   * **Aturan Proteksi Penurunan Impulsif (Anti-Falling-Knife):**
     Jika $\Delta P_{H1} \le -\$4.50$, struktur pasar secara otomatis dikunci ke **`STRONG_BEARISH`**, sehingga seluruh entri BUY melawan arus tren **100% diblokir secara dinamis**.
   * **Aturan Proteksi Kenaikan Impulsif (Anti-Runaway-Train):**
     Jika $\Delta P_{H1} \ge +\$4.50$, struktur pasar dikunci ke **`STRONG_BULLISH`**, sehingga seluruh entri SELL melawan reli cepat (seperti 26 Oktober) otomatis diblokir.
   * **Kondisi Normal / Sideway:**
     Pada kondisi pasar sideway normal (seperti Juli & November di mana fluktuasi 1 jam hanya \$1.50 – \$3.00), detektor tetap berada pada status `NEUTRAL` dan seluruh transaksi pemenang dieksekusi 100% tanpa hambatan.

---

## 3. Matriks Hasil Pengujian Empiris (Anti-Regression Matrix)

| Bulan / Periode | Metrik Baseline EXP-12 | Metrik EXP-16 (Structural Adaptation) | Evaluasi Kepatuhan Hukum Mutlak |
| :--- | :---: | :---: | :---: |
| **November 2026** (Alpha Sideway) | 51 Trade \| Net **+\$1.056,69** \| PF 3,35 \| DD 3,43% | 45 Trade \| Net **+\$1.078,86** \| PF **3,83** \| DD **3,29%** | ✅ **HUKUM 1 LULUS:** Profit naik +\$22,17, PF melonjak ke 3,83 |
| **Oktober 2026** (Pre-Election Cascades) | 225 Trade \| Net **-\$1.293,47** \| PF 0,58 \| DD 20,77% | 187 Trade \| Net **-\$152,75** \| PF **0,93** \| DD **13,31%** | ✅ **HUKUM 2 LULUS:** Kerugian terpangkas 88,2% (+\$1.140 terselamatkan!), SELL berbalik untung +\$267 |
| **Juli 2026** (Alpha Champion) | 282 Trade \| Net **+\$2.477,79** \| PF 1,82 \| DD 14,80% | *Sedang dieksekusi (Task-745)* | *Verifikasi Anti-Regresi* |

---

## 4. Rencana Validasi Menyeluruh Melintasi Seluruh Bulan (Hukum 3)

Segera setelah verifikasi silang pada bulan Juli selesai:
1. Jalankan audit longitudinal kontinu 8 bulan penuh (**01 April s/d 06 November 2026, 53.541.349 tick riil**) via `scratch/run_full_8month_structural_audit.py`.
2. Evaluasi pertumbuhan modal kontinu carryover (\$10.000 modal awal).
3. Catat hasil final ke dalam `docs/EXPERIMENT_REGISTRY.md`.
