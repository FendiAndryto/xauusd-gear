# Spesifikasi Teknis & Daftar Tiket: Fase E
## EXP-05: Synergistic Step-Lock Scalper & Rollover Protected Engine

**Proyek:** XAUUSD Quantitative Scalping Research Platform  
**Fase:** Fase E - Synthesis of Alpha Findings (Restored Range Sweet Spot, Rollover Blackout & Step-Lock Runner)  
**Versi Dokumen:** 1.0.0  
**Tanggal:** 2026-11-07  
**Status Target:** Validasi Walk-Forward Analysis (WFA) pada 6.612.042 Tick Riil Exness  

---

## 1. Filosofi & Hipotesis Kuantitatif

Dari 4 eksperimen sebelumnya (`EXP-01` s/d `EXP-04`), kita telah mengisolasi secara empiris variabel mana yang menciptakan alpha dan variabel mana yang merusak ekspektansi:

1. **Range Sweet Spot (\$3.00 – \$10.00):**
   * Di `EXP-03`, rentang \$3.00–\$10.00 menghasilkan **+\$431.75** (PF 1.15) karena frekuensi pantulan sideway emas sangat padat di rentang \$3.50–\$4.50.
   * Di `EXP-04`, menaikkan batas bawah ke \$5.00 menghilangkan 30%+ peluang setup menguntungkan ini. Oleh karena itu, rentang \$3.00–\$10.00 dikembalikan sebagai sweet spot utama.
2. **Rollover Blackout Only (21:00–23:00 UTC / 04:00–06:00 WIB):**
   * Sesi Asia (06:00–14:00 WIB) terbukti menghasilkan pantulan sideway yang bersih dan tidak boleh dipotong ukuran lotnya ke 50%.
   * Namun, pada jam rollover (04:00–06:00 WIB), spread Exness melonjak hingga \$0.60–\$0.70. Hanya 2 jam inilah yang wajib diblokir dari pembukaan entri baru.
3. **Step-Lock Runner Protection Architecture:**
   * Hasil empiris `EXP-04` membuktikan bahwa *Strict Breakeven* di harga entri merusak rasio Win/Loss dari 3.05x menjadi 2.17x akibat *micro-whipsaw*.
   * Arsitektur `STEP_LOCK` adalah formula ideal:
     - **Saat TP1 tercapai ($E_Q$):** Tutup posisi terawal (Layer 1). Jangan sentuh SL layer berikutnya agar posisi tetap memiliki ruang bernapas.
     - **Saat TP2 tercapai (Batas Seberang):** Tutup Layer 2. Kunci SL Layer 3 (Runner) ke level $E_Q$. Posisi runner kini 100% *risk-free* dan mengunci profit setengah range sambil mengejar target ekspansi.

---

## 2. Work Breakdown Structure (Daftar Tiket Fase E)

| ID | Judul Tiket | Scope Utama | Output | Status |
| :--- | :--- | :--- | :--- | :---: |
| `TICK-501` | Phase E Specification & Architecture Blueprint | Dokumen spesifikasi parameter final, matriks risiko, dan arsitektur eksekusi terpadu. | `docs/PHASE_5_SPECIFICATION.md` + Artifact | **IN PROGRESS** |
| `TICK-502` | RangeSweepScalperV4 Implementation | Kelas strategi terpadu dengan sweet spot \$3–\$10, full volume Asia, rollover blackout, dan Step-Lock runner. | `src/strategies/range_sweep_scalper_v4.py` | **PENDING** |
| `TICK-503` | Step-Lock Scalper Unit Verification | Pengujian unit komprehensif untuk lifecycle Step-Lock, rollover gate, dan trigger TP1/TP2. | `tests/test_range_sweep_scalper_v4.py` | **PENDING** |
| `TICK-504` | EXP-05 Walk-Forward Benchmark Runner | Eksekusi benchmark WFA (70% In-Sample / 30% Out-of-Sample) pada 6,6 juta tick riil Exness. | `scripts/run_experiment_exp05.py` | **PENDING** |
| `TICK-505` | Master Registry & Leaderboard Evaluation | Analisis komparatif menyeluruh melawan EXP-01 s/d EXP-04, tear-sheet pelaporan, dan update registry. | `docs/EXPERIMENT_REGISTRY.md` + Tear-sheet | **PENDING** |

---

## 3. Rincian Kriteria Penerimaan (DoD) Tiap Tiket

### `TICK-501`: Spesifikasi Teknis
* [x] Dokumen spesifikasi teknis dan tiket terbit di `docs/PHASE_5_SPECIFICATION.md`.
* [x] Artifact tersinkronisasi di brain conversation.

### `TICK-502`: `RangeSweepScalperV4`
* **Spesifikasi:**
  - `lookback_minutes = 30`
  - `min_range_usd = 3.0` | `max_range_usd = 10.0`
  - `min_sweep_usd = 0.75` | `max_sweep_usd = 2.00`
  - `hard_sl_offset_usd = 1.20` | `layer_spacing_usd = 0.50`
  - `layer_volumes = [0.05, 0.10, 0.15]`
  - `cooldown_seconds = 1200.0` (20 menit setelah boundary SL terkena)
  - `be_policy = "STEP_LOCK"`
  - `allowed_hours_utc = set(range(0, 21)) | {23}` (Rollover jam 21 & 22 diblokir, jam 23 s/d 20 aktif penuh 100% volume).
* **Acceptance Criteria:**
  - [ ] Implementasi class mewarisi `BaseStrategy`.
  - [ ] Mengatur order flow secara deterministik tanpa race condition.

### `TICK-503`: Unit Verification
* **Acceptance Criteria:**
  - [ ] Test mensimulasikan setup sell/buy, TP1 tercapai tanpa mengubah SL, dan TP2 tercapai mengunci runner.
  - [ ] Test memverifikasi jam rollover (21 & 22 UTC) menolak pembukaan posisi.
  - [ ] Lolos 100% pytest suite.

### `TICK-504`: Benchmark WFA pada 6,6 Juta Tick
* **Acceptance Criteria:**
  - [ ] Eksekusi In-Sample (Oktober 2026, 4,62M tick) dan Out-of-Sample (November 2026, 1,98M tick).
  - [ ] Ekspor log transaksi CSV dan kurva ekuitas di `reports/experiments/EXP-05/`.

### `TICK-505`: Evaluasi & Leaderboard Update
* **Acceptance Criteria:**
  - [ ] Perbandingan side-by-side dengan EXP-01, EXP-02, EXP-03, dan EXP-04.
  - [ ] Perekaman hasil ke `docs/EXPERIMENT_REGISTRY.md` dan artifact.
