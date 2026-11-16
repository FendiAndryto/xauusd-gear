# Master Engineering Ticket Suite: Phase P (EXP-17)
## EPIC-EXP17: Asymmetric Bullish Expansion Gate & Midnight Boundary Maturity Engine

**Epic ID:** `EPIC-EXP17`  
**Master Ticket:** `TICK-1301`  
**Tipe:** Core Strategy Enhancement & Longitudinal Multi-Month Audit  
**Prioritas:** P0 (Highest Priority - Production Readiness Sprint)  
**Doktrin Tertinggi:** [AGENTS.md](../AGENTS.md) — Tiga Hukum Mutlak Penelitian  
**Spesifikasi Teknis:** [PHASE_15_SPECIFICATION.md](PHASE_15_SPECIFICATION.md)  
**Status:** READY FOR IMPLEMENTATION  
**Target Rilis:** EXP-17 Production Candidate  

---

## 1. Ringkasan Eksekutif (Epic Story)

Sebagai Quantitative Portfolio Manager dan Algorithmic Trading Engineer, saya ingin mengintegrasikan **Asymmetric Bullish Expansion Gate ($DayDisp \ge +\$25.00$)** dan **Midnight Boundary Maturity Filter (00:00–00:15 UTC)** ke dalam strategi `RangeSweepScalperV8`, agar:
1. Posisi SELL terlindungi dari tertabrak reli emas parabolik (membalikkan defisit di Juni, Agustus, dan September).
2. Jebakan *ghost range* tengah malam sesi Sydney tereliminasi.
3. Seluruh 8 bulan pengujian (April–November 2026, 53,54M tick riil Exness) mencapai target **All-Green / Near-Zero Loss** tanpa membatalkan alpha kemenangan November (+$1.072), Juli (+$308+), dan Oktober (+$91).
4. Tidak ada pemotongan kalender statis (Hari Senin 100% Aktif).

---

## 2. Rincian Tiket Modular (Breakdown of Sub-Tickets)

```
┌────────────────────────────────────────────────────────────────────────┐
│               EPIC-EXP17: THE ALL-GREEN SPRINT (TICK-1301)             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
    ┌───────────────────────────────┼───────────────────────────────┐
    │                               │                               │
    ▼                               ▼                               ▼
[TICK-1701]                     [TICK-1702]                     [TICK-1703]
Mathematic Model &              Core Integration:               Anti-Regression Cross-
Sensitivity Analysis            RangeSweepScalperV8             Validation (Nov & Jul)
    │                               │                               │
    └───────────────────────────────┼───────────────────────────────┘
                                    │
    ┌───────────────────────────────┴───────────────────────────────┐
    │                                                               │
    ▼                                                               ▼
[TICK-1704]                                                     [TICK-1705]
Full 8-Month 53.54M Tick                                        Ledger Reconciliation &
Simulation Runner                                               Leaderboard Reporting
```

---

### `TICK-1701`: Formulasi Matematika & Analisis Sensitivitas Ambang Batas Bullish Gate
* **Tipe:** Task / Quantitative Research
* **Komponen:** `scratch/test_bullish_expansion_gate.py`
* **Deskripsi:**
  Menguji ambang batas deviasi harga harian emas terhadap Day Open ($DayDisp$) pada rentang nilai +\$20.00, +\$25.00, dan +\$30.00 di bulan Agustus (reli +\$678) dan Juni 2026 (reli akhir kuartal).
* **Kriteria Keberhasilan (Acceptance Criteria):**
  - [ ] Terbukti memblokir pembukaan posisi SELL pada hari 5 Agustus 2026 ($DayDisp > +\$25.00$).
  - [ ] Memastikan posisi SELL yang menguntungkan pada hari normal (seperti 8 Juli dan 11 November) tidak terblokir prematur.
  - [ ] Menentukan nilai ambang optimal: `max_bull_disp_usd = 25.00`.
* **Definition of Done:** Skrip riset berhasil dieksekusi dan mengeluarkan matriks perbandingan PnL.

---

### `TICK-1702`: Integrasi Bullish Expansion Gate & Midnight Maturity ke Core Engine
* **Tipe:** Feature / Core Strategy Upgrade
* **Komponen:** `src/strategies/range_sweep_scalper_v8.py`
* **Deskripsi:**
  1. Tambahkan parameter `max_bull_disp_usd: float = 25.00` pada konstruktor `RangeSweepScalperV8`.
  2. Implementasikan evaluasi gating pada pembukaan posisi SELL:
     ```python
     can_sell = can_sell and not (self.max_bull_disp_usd > 0 and day_disp >= self.max_bull_disp_usd)
     ```
  3. Tambahkan parameter `midnight_warmup_minutes: int = 15`.
  4. Blokir pembukaan setup baru jika $Hour == 0$ dan $Minute < midnight\_warmup\_minutes$.
* **Kriteria Keberhasilan (Acceptance Criteria):**
  - [ ] Parameter `max_bull_disp_usd` dan `midnight_warmup_minutes` terdokumentasi dan memiliki default yang aman.
  - [ ] Logika gating dievaluasi dalam waktu streaming $O(1)$ tanpa latensi komputasi tambahan.
  - [ ] Semua unit test yang ada tetap lolos tanpa regresi.
* **Definition of Done:** Kode lolos uji linting dan unit test di `tests/test_range_sweep_scalper_v8.py`.

---

### `TICK-1703`: Test Suite Validasi Silang Anti-Regresi (HUKUM 1)
* **Tipe:** Testing / Quality Assurance
* **Komponen:** `tests/test_exp17_anti_regression.py`
* **Deskripsi:**
  Membuat test suite deterministik untuk memverifikasi bahwa penambahan *Bullish Expansion Gate* dan *Midnight Maturity Check* **TIDAK MENGURANGI** profit pada bulan-bulan yang sudah menang.
* **Kriteria Keberhasilan (Acceptance Criteria):**
  - [ ] November 2026 (3,18M tick riil): Net PnL tetap $\ge +\$1.070,00$ dan Profit Factor $\ge 4.0$.
  - [ ] Juli 2026 (6,72M tick riil): Net PnL tetap $\ge +\$300,00$.
  - [ ] Oktober 2026 (10,15M tick riil): Net PnL tetap Positif ($> +\$90,00$).
  - [ ] Memastikan tidak ada anomali *multi-fill sub-second order* (Anti-Burst Cooldown 60s aktif).
* **Definition of Done:** `pytest tests/test_exp17_anti_regression.py` keluar dengan status PASSED (Exit Code 0).

---

### `TICK-1704`: Runner Simulasi Longitudinal Kontinu 8 Bulan (53.54M Tick)
* **Tipe:** Benchmark Runner
* **Komponen:** `scripts/run_experiment_exp17.py`
* **Deskripsi:**
  Mengeksekusi simulasi carryover kontinu 8 bulan penuh (April s/d November 2026, total 53.541.749 tick riil Exness) dengan modal awal \$10.000,00, memperhitungkan spread riil broker dan latensi 50–120 ms.
* **Kriteria Keberhasilan (Acceptance Criteria):**
  - [ ] Menghitung ekuitas carryover dari bulan ke bulan secara otomatis.
  - [ ] Mengeluarkan output tabel Rich Console sesuai format Bagian 5 `AGENTS.md`.
  - [ ] Menyimpan ringkasan komputasi ke `reports/exp17_monthly_summary.json` dan CSV trades/equity per bulan di `reports/experiments/EXP-17/month_XX/`.
* **Definition of Done:** Skrip selesai dieksekusi melintasi seluruh 8 bulan tanpa error memori dan menghasilkan output artefak lengkap.

---

### `TICK-1705`: Rekonsiliasi Buku Besar & Pelaporan Standar Baku `AGENTS.md`
* **Tipe:** Documentation & Reporting
* **Komponen:** `docs/EXPERIMENT_REGISTRY.md`, Chat Response Presentation
* **Deskripsi:**
  Mencatat hasil final EXP-17 ke dalam Master Experiment Registry dan menyajikan laporan 3 elemen wajib sesuai Doktrin Bagian 5 `AGENTS.md`.
* **Kriteria Keberhasilan (Acceptance Criteria):**
  - [ ] Tabel Ekuitas Berkelanjutan Bulanan (*Continuous Monthly Equity Carryover Table*) terisi lengkap dari April s/d November 2026.
  - [ ] Tabel Rincian Arah Transaksi (BUY vs SELL Breakdown) per bulan tersaji lengkap.
  - [ ] Audit Forensik Mendalam memvalidasi keberhasilan adaptasi struktural.
  - [ ] Status Kelulusan EXP-17 diputuskan (LULUS / PRODUCTION-READY).
* **Definition of Done:** `docs/EXPERIMENT_REGISTRY.md` terupdate dan terverifikasi bersih.
