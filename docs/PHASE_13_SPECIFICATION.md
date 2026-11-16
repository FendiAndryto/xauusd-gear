# Spesifikasi Teknis & Daftar Tiket: Fase N
## EXP-15: Pure Asymmetric Shield Engine (Single-Engine Production Architecture)

**Proyek:** XAUUSD Quantitative Scalping Research Platform  
**Fase:** Fase N (EXP-15: Pure Asymmetric Shield Scalper)  
**Versi Dokumen:** 1.0.0  
**Tanggal:** 2026-11-08  
**Status Target:** Validasi Komparatif Longitudinal pada 53.541.349 Tick Riil Exness (`XAUUSDm`, April – November 2026)  

---

## 1. Latar Belakang & Diagnosa Kritis (Post EXP-12 s/d EXP-14)

Riset longitudinal 8 bulan (April–November 2026) melintasi 53,54 juta tick riil Exness membuktikan fakta-fakta kuantitatif krusial:

1. **Eliminasi Total Engine B (The Retest Paradox in Gold):**
   * Pada pengujian **EXP-14**, Engine B (*Breakout Retest Scalper*) diberi wewenang penuh mengeksekusi order saat tren terkonfirmasi.
   * Hasilnya: Engine B mencatat **471 trade dengan kerugian bersih -$1.257,17** (Win Rate ~30%).
   * *Akar Penyebab:* Volatilitas intrahari emas (M1–M5) memiliki noise alami sebesar **$2.00 s/d $4.50**. Memasang Stop Loss ketat ($1.50) pada entri retest menyebabkan posisi terkena *whipsaw tax* berulang kali sebelum tren makro sempat berkembang.
   * *Keputusan:* **Engine B dieliminasi total secara permanen** dari arsitektur eksekusi.

2. **Peran Sejati Wasit ORB Adalah "Perisai" (The ORB Protective Shield):**
   * Wasit ORB London (07:00–08:00 UTC, ambang batas $4.00) terbukti secara matematis **bukanlah mesin pembuka posisi breakout**.
   * Kekuatan kuantitatif terbesarnya adalah sebagai **Perisai Pelindung**: saat harga emas mengalami reli ekspansi satu arah (seperti reli Agustus +$678), Wasit mengunci bot dan mematikan Engine A dari melakukan *counter-trend fading*.
   * Perisai ini memangkas kerugian bulan-bulan tren ekstrem hingga >60%.

3. **Evaluasi Jam & Hari Beracun (Toxic Microstructure Windows):**
   * **Hari Senin:** Menyumbang akumulasi kerugian **-$1.277,08** (Win Rate hanya 14,2%) akibat penyesuaian gap akhir pekan dan likuiditas tipis sesi pembukaan. Di bulan Oktober saja, hari Senin menyumbang kerugian -$842,89 (65% dari total loss bulan tersebut).
   * **Jam 00:00–02:59 UTC (07:00–09:59 WIB):** Sesi Sydney/Asia awal menyumbang akumulasi kerugian **-$1.024,12** (Win Rate 17,2%) akibat likuiditas tipis dan spread fluktuatif.
   * **Jam 08:00–08:59 UTC (15:00–15:59 WIB):** Jam lelang emas pagi London (*LBMA Gold Price AM Fixing*) menyumbang kerugian **-$616,84** (Win Rate hanya 11,3%) akibat lonjakan slippage lelang.
   * **Jam Beracun yang Sudah Terbukti Diblokir:** Jam 12:00 UTC (Rilis Berita AS), Jam 19:00 UTC (Wall Street afternoon churn), dan Jam 21:00–22:59 UTC (Rollover broker spread spike).

4. **Pencegahan Anomali Eksekusi (Anti-Burst Cooldown):**
   * Pada audit data tick EXP-12 tanggal 08 Juli 2026, tercatat adanya 11 order pada Layer 3 yang terisi di sub-detik yang sama akibat osilasi harga cepat melewati ambang batas sebelum status posisi tersinkronisasi.
   * Dibutuhkan mekanisme **Anti-Burst Cooldown** (minimal 60 detik) per layer untuk memastikan eksekusi order benar-benar higienis dan realistis sesuai regulasi broker.

---

## 2. Cetak Biru Arsitektur Baru (`PureShieldScalper` / EXP-15)

Arsitektur `EXP-15` menyederhanakan sistem menjadi **Single Engine murni** dengan pengamanan berlapis:

```
                                  ┌──────────────────────────────────────────────┐
                                  │           INCOMING REAL TICK EVENT           │
                                  │   (Bid, Ask, Spread, Timestamp Microsecond)  │
                                  └──────────────────────┬───────────────────────┘
                                                         │
                                                         ▼
                                  ┌──────────────────────────────────────────────┐
                                  │ [GATE 1] Spread Filter (spread <= $0.25)     │
                                  └──────────────────────┬───────────────────────┘
                                                         │ PASS
                                                         ▼
                                  ┌──────────────────────────────────────────────┐
                                  │ [GATE 2] Temporal & Day-of-Week Gatekeeper   │
                                  │ - Monday Mode: OFF / AFTERNOON_ONLY (>= 12h) │
                                  │ - Blackout: {0, 1, 2, 8, 12, 19, 21, 22} UTC │
                                  └──────────────────────┬───────────────────────┘
                                                         │ PASS
                                                         ▼
                                  ┌──────────────────────────────────────────────┐
                                  │ [GATE 3] Institutional Daily Circuit Breaker  │
                                  │ - Daily Realized Loss Limit: -$150.00        │
                                  └──────────────────────┬───────────────────────┘
                                                         │ PASS
                                                         ▼
                                  ┌──────────────────────────────────────────────┐
                                  │ [GATE 4] Wasit London ORB Protective Shield   │
                                  │ - London 07:00-08:00 UTC Anchor ($4.00 range)│
                                  │ - Breakout detected -> LOCK ALL COUNTER-TRADE│
                                  └──────────────────────┬───────────────────────┘
                                                         │ CLEAR (RANGE REGIME)
                                                         ▼
                                  ┌──────────────────────────────────────────────┐
                                  │ [CORE ENGINE] Engine A: RangeSweepScalperV8  │
                                  │ - 30-Minute S/R Reference ($3.00 to $10.00)  │
                                  │ - Liquidity Sweep Rejection ($0.75 - $2.00)  │
                                  │ - Asymmetric Step-Lock Breakeven (Payoff 3x) │
                                  │ - Layer Spacing $0.50 + Anti-Burst Cooldown  │
                                  └──────────────────────────────────────────────┘
```

---

## 3. Spesifikasi Teknis Komponen

### 3.1 Eliminasi Total Engine B
* Menghapus seluruh dependensi ke `VolatilityBreakoutScalperV1`.
* Tidak ada pemantauan retest, tidak ada order breakout, dan tidak ada piramidisasi Anti-Martingale.
* Mengurangi kompleksitas state machine dan komputasi CPU per tick secara signifikan.

### 3.2 In-Line Wasit ORB Protective Shield
* Wasit ORB beroperasi secara *in-line* di dalam strategi utama.
* Jam jangkar: **07:00 s/d 08:00 UTC**.
* Ambang batas breakout: **`orb_threshold_usd = 4.00`**.
* Aturan proteksi:
  * Jika harga menembus `orb_high + $4.00`: Status **TRENDING_BULLISH**. Seluruh entri SELL (counter-trend) **DIBLOKIR TOTAL**. Hanya entri BUY pada dip ekstrim yang diperbolehkan (jika memenuhi syarat sweep).
  * Jika harga menembus `orb_low - $4.00`: Status **TRENDING_BEARISH**. Seluruh entri BUY (counter-trend) **DIBLOKIR TOTAL**. Hanya entri SELL pada rally yang diperbolehkan.
  * Jika di dalam batas: Status **BALANCED_RANGE**. Kedua arah BUY dan SELL aktif penuh.

### 3.3 Enhanced Temporal Filters (Hari & Jam)
1. **Parameter `monday_mode`:**
   * `"OFF"` (Default Rekomendasi): Seluruh hari Senin (00:00 s/d 23:59 UTC) dimatikan total. Menghilangkan 113 trade beracun dengan kerugian -$1.277.
   * `"AFTERNOON_ONLY"`: Hari Senin hanya aktif setelah pukul 12:00 UTC (membuang sesi pagi yang penuh risiko gap).
2. **Extended Blackout Hours (`blackout_hours_utc`):**
   * Himpunan jam wajib blokir: `{0, 1, 2, 8, 12, 19, 21, 22}` UTC.
     * `0, 1, 2`: Likuiditas tipis sesi Sydney/Asia awal.
     * `8`: Lonjakan volume lelang pagi London (*LBMA Gold Price Fixing*).
     * `12`: Rilis berita data makro AS.
     * `19`: Rotasi churn penutupan sore New York.
     * `21, 22`: Jam pelebaran spread rollover broker.

### 3.4 Anti-Burst Cooldown & Eksekusi Higienis
* Menambahkan atribut `layer_cooldown_seconds = 60.0` pada setiap layer.
* Jika suatu layer (misal Layer 1) baru saja dieksekusi atau ditutup, layer berikutnya atau layer yang sama memiliki jeda minimum 60 detik sebelum order baru dapat dipicu pada harga yang sama.
* Mencegah anomali multi-fill sub-detik yang tidak realistis pada data tick frekuensi tinggi.

### 3.5 Institutional Daily Circuit Breaker
* Mempertahankan batas kerugian harian: `max_daily_loss_usd = $150.00`.
* Menghitung akumulasi PnL harian secara real-time ($O(1)$).
* Begitu kerugian mencapai -$150.00, seluruh aktivitas pembukaan posisi baru dihentikan hingga reset otomatis pada 00:00 UTC hari berikutnya.

---

## 4. Work Breakdown Structure (Daftar Tiket Fase 13 / N)

| ID | Judul Tiket | Lingkup Kerja Utama | File Output | Status |
| :--- | :--- | :--- | :--- | :---: |
| `TICK-1301` | Technical Specification & Blueprint Document | Pembuatan dokumen spesifikasi teknis EXP-15, eliminasi Engine B, dan filter temporal. | `docs/PHASE_13_SPECIFICATION.md` | **DONE** |
| `TICK-1302` | Pure Shield Scalper Strategy Implementation | Mengembangkan strategi `PureShieldScalper` (Single Engine A + In-line Wasit ORB Shield + Anti-Burst Cooldown). | `src/strategies/pure_shield_scalper.py` | **DONE** |
| `TICK-1303` | Temporal Filter & Monday-Mode Integration | Implementasi konfigurasi `monday_mode` ('OFF'/'AFTERNOON_ONLY') dan `EXTENDED_BLACKOUT_HOURS_UTC`. | `src/strategies/pure_shield_scalper.py` | **DONE** |
| `TICK-1304` | Unit & Invalidation Test Suite | Pengujian unit deterministik: ORB shield gating, Monday modes, extended blackout, anti-burst cooldown, dan circuit breaker. | `tests/test_pure_shield_scalper.py` | **DONE** |
| `TICK-1305` | EXP-15 8-Month Longitudinal Benchmark Runner | Script eksekusi benchmark kontinu 8 bulan (April–November 2026, 53,54M tick riil Exness). | `scripts/run_experiment_exp15.py` | **DONE** |
| `TICK-1306` | Comprehensive Reconciliation & Ledger Update | Analisis komparatif head-to-head EXP-12 vs EXP-13 vs EXP-15 dan pembaruan Master Experiment Registry. | `reports/experiments/EXP-15/`, `docs/EXPERIMENT_REGISTRY.md` | **DONE** |

---

## 5. Kriteria Keberhasilan & Syarat Kelulusan (Definition of Done)

1. **Integritas Arsitektur:**
   * Engine B terbukti tereliminasi 100% (tidak ada kelas breakout/pyramiding yang diinisialisasi atau dipanggil).
   * Wasit ORB terbukti memblokir posisi counter-trend saat terjadi breakout London.
   * Tidak ada satu pun transaksi yang terjadi di hari Senin (jika mode OFF) atau di jam blackout `{0, 1, 2, 8, 12, 19, 21, 22}` UTC.
2. **Kinerja Kuantitatif Longitudinal (53,54 Juta Tick):**
   * **Net Profit Kumulatif 8 Bulan:** Diproyeksikan menembus **+$2.500 s/d +$3.200 (+25% s/d +32% Return)** bersih dari spread & slippage.
   * **Max Drawdown Kumulatif:** Terkendali secara ketat di kisaran **5,0% s/d 8,5%** (jauh lebih aman dari EXP-12 yang 15,88%).
   * **Profit Factor (PF):** Konsisten berada di atas **> 1,30**.
   * **Win/Loss Payoff Ratio:** Bertahan kokoh di atas **> 3,0x**.
3. **Stabilitas Produksi:**
   * Seluruh unit test pada `tests/test_pure_shield_scalper.py` lulus 100% tanpa regresi.
