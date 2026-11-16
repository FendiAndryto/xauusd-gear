# Master Engineering Ticket Suite: Standalone Research Track
## EPIC-SMC: Multi-Timeframe SMC Scalper Engine (D1 - H1 - M5/M1)

**Track:** Independent Strategy Research (Track SMC)  
**Epic ID:** `EPIC-SMC`  
**Master Ticket:** `TICKET-SMC-01`  
**Tipe:** New Standalone Quantitative Strategy Suite  
**Prioritas:** P0 (Highest Priority - Independent Clean-Slate Development)  
**Dokumen Acuan:**
- Doktrin Tertinggi: [AGENTS.md](../AGENTS.md)
- Cetak Biru Fondasi: [BLUEPRINT_D1_H1_M5_SMC.md](BLUEPRINT_D1_H1_M5_SMC.md)
- Spesifikasi Teknis: [SPECIFICATION_MTF_SMC.md](SPECIFICATION_MTF_SMC.md)  
**Status:** READY FOR IMPLEMENTATION  

---

## 1. Ringkasan Eksekutif (Epic Story)

Membangun modul robot kuantitatif XAUUSD yang **berdiri sendiri (100% mandiri, bebas dari kode & iterasi eksperimen masa lalu)** dengan arsitektur murni *Smart Money Concepts (SMC)* dan *Auction Market Theory*.

Strategi ini beroperasi dengan memadukan 4 lapisan timeframe secara simultan:
1. **D1:** Menentukan batas likuiditas eksternal hari sebelumnya (PDH & PDL) dengan algoritma rekursif *Mother Bar Fallback* untuk menangani kondisi *Inside Day / Sideway*.
2. **H1:** Membaca *Order Flow* dan bias arah utama pasar (Bullish, Bearish, atau Range).
3. **M15/M5:** Mendeteksi karakter interaksi harga di batas D1: *Liquidity Sweep (Rejection)* atau *Value Acceptance (Breakout Expansion)*.
4. **M5/M1:** Memvalidasi *Change of Character (CHoCH)* dengan displacement dan memetakan zona *Order Block (OB)* segar (*unmitigated*) lengkap dengan *Fair Value Gap (FVG)*.
5. **Eksekusi Pending Limit Piramida:** Layer 1 pada Open OB (Risiko 1.0%) dan Layer 2 pada 50% Mean Threshold OB (Risiko 1.5%), dengan Stop Loss terproteksi di pucuk ekor sweep.
6. **Mekanisme Hybrid Exit:** TP 1 parsial 50% di Equilibrium 50% D1 / RR 1:2 + geser SL ke BEP (Risk-Free), dan TP 2 runner di likuiditas seberang (PDL/PDH).
7. **Circuit Breakers & Financial Discipline:** Target profit harian maksimal **+10%** (otomatis *hard lock & sleep mode*), batas maksimal *Daily Drawdown* **-7.5% s/d -12.5%** (otomatis *hard stop* harian), serta proteksi *Spread Guard* $\le 3.5$ pips untuk operasional 24 jam non-stop.

---

## 2. Struktur Sub-Tiket Modular (Clean Architecture)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                 EPIC-SMC: STANDALONE MTF SMC SCALPER                    │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
     ┌───────────────────────────────┼───────────────────────────────┐
     │                               │                               │
     ▼                               ▼                               ▼
[TICK-SMC-01]                   [TICK-SMC-02]                   [TICK-SMC-03]
D1 Boundary & Mother Bar        H1 Order Flow & Bias            M15/M5 Sweep vs
Fallback Extractor              Direction Classifier            Acceptance Engine
     │                               │                               │
     └───────────────────────────────┼───────────────────────────────┘
                                     │
     ┌───────────────────────────────┼───────────────────────────────┐
     │                               │                               │
     ▼                               ▼                               ▼
[TICK-SMC-04]                   [TICK-SMC-05]                   [TICK-SMC-06]
M5/M1 CHoCH & Order             Layered Pyramid Limit           Hybrid TP (50% + BEP)
Block (OB + FVG) Mapper         Execution & Canceller           & Extreme Sweep Wick SL
     │                               │                               │
     └───────────────────────────────┼───────────────────────────────┘
                                     │
     ┌───────────────────────────────┴───────────────────────────────┐
     │                                                               │
     ▼                                                               ▼
[TICK-SMC-07]                                                   [TICK-SMC-08]
Daily Financial Guard (+10% Win Cap                             Standalone Backtester &
& -7.5% - 12.5% Circuit Breaker + Spread)                       AGENTS.md Continuous Ledger Audit
```

---

## 3. Rincian Sub-Tiket

### `TICK-SMC-01`: D1 Boundary & Recursive Mother Bar Extractor
* **Tipe:** Core Feature / Data Processing
* **Komponen:** `src/strategies/smc/d1_boundary_extractor.py`
* **Deskripsi:** 
  Mengekstrak Previous Day High (PDH), Previous Day Low (PDL), dan Equilibrium (50% Range). 
  Jika candle D1 kemarin adalah *Inside Bar* ($High_{d-1} < High_{d-2}$ dan $Low_{d-1} > Low_{d-2}$), fungsi akan berjalan rekursif ke belakang hingga menemukan *Mother Bar* terluar yang membungkus seluruh inside bar.
* **Kriteria Keberhasilan (Acceptance Criteria):**
  - [ ] Mendeteksi single maupun multiple consecutive Inside Days secara rekursif.
  - [ ] Menghasilkan level PDH, PDL, dan Eq (50%) deterministik pada pergantian hari (00:00 UTC).
* **Definition of Done:** Unit test `tests/smc/test_d1_boundary_extractor.py` lolos.

---

### `TICK-SMC-02`: H1 Order Flow & Bias Direction Classifier
* **Tipe:** Feature / Trend Bias Module
* **Komponen:** `src/strategies/smc/h1_bias_classifier.py`
* **Deskripsi:**
  Mengklasifikasikan arah struktur tren pada H1:
  - `BULLISH_BIAS`: Higher Highs (HH) & Higher Lows (HL) atau harga di atas EMA 20 H1.
  - `BEARISH_BIAS`: Lower Highs (LH) & Lower Lows (LL) atau harga di bawah EMA 20 H1.
  - `NEUTRAL_RANGE`: Harga berada dalam konsolidasi ketat.
* **Kriteria Keberhasilan (Acceptance Criteria):**
  - [ ] Evaluasi bias dalam $O(1)$ streaming time.
  - [ ] Memberikan bobot probabilitas untuk validasi setup Reversal vs Continuation.
* **Definition of Done:** Unit test `tests/smc/test_h1_bias_classifier.py` lolos.

---

### `TICK-SMC-03`: M15/M5 Sweep vs Acceptance Classification Engine
* **Tipe:** Feature / Price Action State Machine
* **Komponen:** `src/strategies/smc/sweep_acceptance_engine.py`
* **Deskripsi:**
  Mengklasifikasikan reaksi harga saat menembus PDH atau PDL:
  - `SWEEP_REJECTION`: Ekor menembus level, tapi candle close kembali di dalam range dengan $\text{Wick-to-Body Ratio} \ge 0.50$.
  - `VALUE_ACCEPTANCE`: Body candle tebal close di luar range dengan volume/displacement signifikan $> 1.5\times \text{ATR}_{14}$.
* **Kriteria Keberhasilan (Acceptance Criteria):**
  - [ ] Mencegah salah sinyal antara false breakout dan real breakout secara matematis.
* **Definition of Done:** Unit test `tests/smc/test_sweep_acceptance_engine.py` lolos.

---

### `TICK-SMC-04`: M5/M1 CHoCH Validation & Order Block (OB + FVG) Mapper
* **Tipe:** Feature / SMC Pattern Recognition
* **Komponen:** `src/strategies/smc/order_block_mapper.py`
* **Deskripsi:**
  1. Mendeteksi Change of Character (CHoCH): Body candle close menembus swing level internal terdekat.
  2. Memetakan zona Order Block (OB): Candle berlawanan terakhir sebelum dorongan impulsif.
  3. Memvalidasi ketiadaan mitigasi (*fresh/unmitigated*) dan keberadaan celah Imbalance (*Fair Value Gap / FVG*).
* **Kriteria Keberhasilan (Acceptance Criteria):**
  - [ ] Menghasilkan koordinat lengkap: `open_price`, `mean_threshold_50`, `extreme_wick_sl`.
  - [ ] Menolak OB yang tidak memiliki displacement atau sudah pernah disentuh harga.
* **Definition of Done:** Unit test `tests/smc/test_order_block_mapper.py` lolos.

---

### `TICK-SMC-05`: Layered Pyramid Limit Execution & Dynamic Cancellation
* **Tipe:** Feature / Order Management System
* **Komponen:** `src/strategies/smc/pyramid_limit_manager.py`
* **Deskripsi:**
  - Layer 1: Limit Order di Open OB (Risiko 1.0% ekuitas).
  - Layer 2: Limit Order di 50% Mean Threshold OB (Risiko 1.5% ekuitas).
  - Total risiko teragregasi: 2.5% per setup.
  - Pembatalan Dinamis: Membatalkan pending order HANYA jika terjadi *Opposite CHoCH* (struktur pasar rusak).
* **Kriteria Keberhasilan (Acceptance Criteria):**
  - [ ] Lot sizing terhitung otomatis berdasarkan jarak harga limit ke SL ekor sweep.
  - [ ] Pembatalan pending order bekerja seketika jika struktur berbalik arah.
* **Definition of Done:** Unit test `tests/smc/test_pyramid_limit_manager.py` lolos.

---

### `TICK-SMC-06`: Hybrid Profit Milestones & Extreme Sweep Wick SL Engine
* **Tipe:** Feature / Trade Management
* **Komponen:** `src/strategies/smc/hybrid_exit_manager.py`
* **Deskripsi:**
  - Menetapkan SL pada ujung ekor Sweep $+ \text{buffer spread}$ (\$0.20 - \$0.30).
  - Milestone 1 (Equilibrium D1 50% atau RR 1:2.0): Tutup 50% volume posisi aktif dan geser SL ke BEP (Risk-Free).
  - Milestone 2 (Likuiditas seberang: PDL untuk SELL, PDH untuk BUY): Tutup 50% sisa posisi (*runner*).
* **Kriteria Keberhasilan (Acceptance Criteria):**
  - [ ] Eksekusi partial close 50% dan geser SL ke BEP berjalan deterministik.
* **Definition of Done:** Unit test `tests/smc/test_hybrid_exit_manager.py` lolos.

---

### `TICK-SMC-07`: Daily Financial Guard (+10% Win Cap, -7.5% s/d -12.5% DD, & Spread Guard)
* **Tipe:** Risk Management & Circuit Breakers
* **Komponen:** `src/strategies/smc/daily_financial_guard.py`
* **Deskripsi:**
  - **Daily Profit Cap:** Jika realized PnL harian $\ge +10.0\%$, tutup semua posisi, cancel pending limit, dan aktifkan status SLEEP hingga 00:00 UTC.
  - **Daily Max Drawdown:** Jika akumulasi kerugian harian mencapai $-7.5\%$ s/d $-12.5\%$, lakukan *hard close* semua posisi dan hentikan trading hari tersebut.
  - **Spread Guard:** Jika spread saat ini $> 3.5$ pips (\$0.35), order dilarang dipasang/dieksekusi.
  - **24 Jam Non-Stop:** Beroperasi di semua sesi (Asia, London, New York) dengan penandaan sesi (*tagging*) pada setiap transaksi.
* **Kriteria Keberhasilan (Acceptance Criteria):**
  - [ ] Sistem memutus arus kerugian harian secara konsisten dan mengunci profit saat target tercapai.
* **Definition of Done:** Unit test `tests/smc/test_daily_financial_guard.py` lolos.

---

### `TICK-SMC-08`: Standalone Backtest Runner & Mandatory AGENTS.md Audit Report
* **Tipe:** System Integration & Benchmark Runner
* **Komponen:** `scripts/run_smc_standalone_benchmark.py`
* **Deskripsi:**
  Menjalankan strategi mandiri ini melintasi seluruh dataset tick riil Exness. Menghasilkan laporan evaluasi sesuai standar baku [AGENTS.md](../AGENTS.md):
  1. *Continuous Monthly Equity Carryover Table* (Modal awal \$10.000).
  2. *BUY vs SELL Breakdown Table*.
  3. *Audit Forensik Mendalam* per sesi dan per bulan.
* **Kriteria Keberhasilan (Acceptance Criteria):**
  - [ ] Eksekusi mulus dari awal hingga akhir tanpa ketergantungan pada strategi lama.
  - [ ] Menghasilkan laporan lengkap di `reports/MTF_SMC_STANDALONE_REPORT.md`.
* **Definition of Done:** Laporan terverifikasi dan memenuhi seluruh standar pelaporan repo.
