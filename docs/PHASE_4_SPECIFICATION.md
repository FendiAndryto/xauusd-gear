# Spesifikasi Teknis & Daftar Tiket: Fase D
## EXP-04: Session-Aware Risk Scaling & Breakeven Empirical A/B Matrix

**Proyek:** XAUUSD Quantitative Scalping Research Platform  
**Fase:** Fase D - Microstructure Session Sizing, Range Sweet Spot, & Breakeven Matrix Optimization  
**Versi Dokumen:** 1.0.0  
**Tanggal:** 2026-11-07  
**Status Target:** Validasi Komparatif Multi-Varian pada 6.612.042 Tick Riil Exness  

---

## 1. Latar Belakang & Hipotesis Kuantitatif

Dari eksperimen sebelumnya (`EXP-03`), metode **Range Boundary Liquidity Sweep 3-Layer** telah membuktikan ketahanan matematisnya dengan mencetak net profit **+$431.75 (+4.32%)**, Profit Factor **1.15**, Win/Loss Ratio **3.05x**, dan Max Drawdown hanya **7.35%** pada data blind test Out-of-Sample (November 2026).

Namun, ada dua tantangan inti yang harus dioptimasi untuk mendongkrak Profit Factor ke target $\ge 1.50$:
1. **Dilema Breakeven (BEP):**
   * *Strict BE* di harga entri sering kali terkena *whipsaw pullback* wajar sebelum emas mencapai TP utama, memotong potensi reward.
   * Sebaliknya, tanpa proteksi sama sekali (*No BE*), posisi yang sudah mengantongi profit di $E_Q$ (TP1) berisiko terbalik menjadi rugi penuh jika terjadi pembalikan mendadak.
   * **Solusi Hipotesis:** Melakukan uji komparatif empiris (*A/B Matrix*) langsung pada data tick riil untuk membandingkan 4 kebijakan proteksi: `NO_BE`, `STRICT_BE`, `BUFFER_BE` (SL dipindahkan ke batas range $R_H$/$R_L$), dan `STEP_LOCK` (kunci berjenjang setelah TP2).
2. **Karakteristik Sesi Pasar (Session-Aware Dynamic Risk):**
   * *Rollover Blackout (21:00–23:00 UTC / 04:00–06:00 WIB):* Spread broker melebar hingga \$0.58–\$0.68. Entri baru wajib diblokir.
   * *Sesi Asia (23:00–07:00 UTC / 06:00–14:00 WIB):* Range relatif rapi namun volume lebih tipis. Mengizinkan entri dengan **diskon volume 50%** dan **maksimal 2 layer** untuk melindungi ekuitas dari pergerakan choppy.
   * *Sesi London/NY Prime (07:00–21:00 UTC / 14:00–04:00 WIB):* Volume dan likuiditas penuh, menerapkan **full 3 layer** dan ukuran lot penuh.
3. **Adaptive Range Sweet Spot:**
   * Membatasi deteksi range pada sweet spot **\$5.00 – \$12.00**.
   * Menolak range $< \$5.00$ (terlalu sempit terhadap spread \$0.24) dan $> \$12.00$ (resiko ekspansi makro).

---

## 2. Work Breakdown Structure (Daftar Tiket Fase D)

| ID | Judul Tiket | Komponen & Scope Utama | Output | Status |
| :--- | :--- | :--- | :--- | :---: |
| `TICK-401` | Session-Aware Risk & Regime Manager | Modul manajemen sesi berbasis waktu UTC/WIB: Rollover blackout, Asian 50% lot/max 2 layers, London/NY full power. | `src/strategies/session_manager.py` + tests | **PENDING** |
| `TICK-402` | Adaptive Range Width Sweet Spot Filter | Pengetatan filter lebar range ($5.00 <= Width <= $12.00) dan validasi stabilitas batas range. | `src/strategies/range_detector.py` update | **PENDING** |
| `TICK-403` | Dynamic Breakeven Policy Engine | Implementasi kebijakan BE modular di `LayerManager`: `NO_BE`, `STRICT_BE`, `BUFFER_BE`, `STEP_LOCK`. | `src/simulator/layer_manager.py` update + tests | **PENDING** |
| `TICK-404` | EXP-04 Multi-Variant Backtest Runner | Eksekusi benchmark A/B testing 4 varian secara paralel/sekuensial pada 6,6 juta tick riil Exness. | `scripts/run_experiment_exp04.py` | **PENDING** |
| `TICK-405` | Empirical Evaluation & Master Registry Update | Analisis komparatif, visualisasi matriks payoff, dan update `EXPERIMENT_REGISTRY.md`. | Laporan tear-sheet + Registry update | **PENDING** |

---

## 3. Rincian Spesifikasi & Acceptance Criteria (DoD) Tiap Tiket

### `TICK-401`: Session-Aware Risk & Regime Manager
* **Spesifikasi:**
  - Class `SessionRegimeManager` mengevaluasi timestamp tick (UTC):
    - `ROLLOVER`: Jam 21:00 s/d 22:59 UTC. Flag `allow_new_entries = False`.
    - `ASIAN`: Jam 23:00 s/d 06:59 UTC. Flag `allow_new_entries = True`, `lot_multiplier = 0.50`, `max_layers = 2`.
    - `PRIME` (London/NY): Jam 07:00 s/d 20:59 UTC. Flag `allow_new_entries = True`, `lot_multiplier = 1.00`, `max_layers = 3`.
* **Acceptance Criteria (DoD):**
  - [ ] Logika transisi jam akurat menangani pergantian hari dan rollover.
  - [ ] Unit test mencakup setiap interval jam dan memverifikasi lot multiplier & max layers.

### `TICK-402`: Adaptive Range Width Sweet Spot Filter
* **Spesifikasi:**
  - Pada `RangeDetector`: parameter `min_range_usd` dinaikkan ke **\$5.00** dan `max_range_usd` disetel ke **\$12.00**.
  - Range di luar rentang ini secara otomatis ditandai `is_ranging = False`.
* **Acceptance Criteria (DoD):**
  - [ ] Filter mendeteksi range $5.00 - $12.00 secara presisi.
  - [ ] Range $4.50 atau $13.00 ditolak tanpa trigger sinyal palsu.

### `TICK-403`: Dynamic Breakeven Policy Engine
* **Spesifikasi:**
  - `LayerManager` menerima konfigurasi `be_policy`:
    1. `"NONE"`: Hard SL tetap di titik invalidasi awal.
    2. `"STRICT"`: Begitu TP1 tercapai ($E_Q$), geser SL posisi tersisa ke $P_{entry} + \Delta_{spread}$.
    3. `"BUFFER"`: Begitu TP1 tercapai ($E_Q$), geser SL posisi tersisa ke level batas range ($R_H$ untuk Sell, $R_L$ untuk Buy). Memberikan toleransi retest tanpa resiko rugi penuh.
    4. `"STEP_LOCK"`: Saat TP1 tercapai, biarkan SL tetap. Hanya ketika TP2 tercapai (batas range seberang), geser SL Layer 3 (runner) ke $E_Q$.
* **Acceptance Criteria (DoD):**
  - [ ] Seluruh 4 varian dieksekusi tanpa error State Machine.
  - [ ] Unit test menguji trigger setiap kebijakan secara eksplisit.

### `TICK-404`: Multi-Variant Backtest Runner
* **Spesifikasi:**
  - Skrip `scripts/run_experiment_exp04.py` memuat data Parquet 6,6 juta tick (Oktober & November 2026).
  - Menjalankan 4 varian secara berurutan dengan parameter yang identik kecuali `be_policy`.
  - Merekam metrik: Net Profit, Profit Factor, Win Rate, Win/Loss Ratio, Trade Count, Max Drawdown, Sharpe Ratio.
* **Acceptance Criteria (DoD):**
  - [ ] Keempat pengujian selesai dan mengekspor log trade ke `reports/experiments/EXP-04/`.
  - [ ] Rekap perbandingan tercetak dalam tabel perbandingan yang rapi.

### `TICK-405`: Evaluation & Master Registry Update
* **Spesifikasi:**
  - Menghitung rasio degradasi WFA (In-Sample vs Out-of-Sample).
  - Menentukan varian pemenang (*Champion Variant*).
  - Memperbarui `docs/EXPERIMENT_REGISTRY.md` dan artifact.
* **Acceptance Criteria (DoD):**
  - [ ] Leaderboard ter-update dengan data presisi.
  - [ ] Kesimpulan kuantitatif dan rekomendasi praktis disajikan ke user.
