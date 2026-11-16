# Spesifikasi Teknis & Daftar Tiket: Fase B (Alpha Research & Microstructure Discovery)

**Proyek:** XAUUSD Tick Scalping Research Platform  
**Fase:** Fase B - Live MT5 Ingestion, Market Microstructure Profiling & Alpha Strategy Research  
**Versi Dokumen:** 1.0.0  
**Tanggal:** 2026-11-07  

---

## 1. Tujuan & Ruang Lingkup

Fase B berfokus pada transisi dari pengujian infrastruktur ke **penemuan edge nyata (*alpha discovery*)** menggunakan data tick riil dari broker MetaTrader 5 yang terpasang di komputer lokal.

Prinsip pengerjaan:
1. **Otomasi Penuh:** Penarikan data tick dilakukan langsung melalui Python MetaTrader 5 API secara otomatis (tanpa ekspor manual oleh user).
2. **Data-Driven Execution Filter:** Strategi tidak akan dibangun "secara buta", melainkan didasarkan pada hasil profiling mikrostruktur spread dan likuiditas broker riil.
3. **Pengerjaan Bertahap Per-Tiket:** Setiap tiket diselesaikan, diverifikasi, dan diuji sebelum melangkah ke tiket berikutnya.

---

## 2. Work Breakdown Structure (Daftar Tiket Fase B)

| ID | Judul Tiket | Scope Utama | Output | Status |
| :--- | :--- | :--- | :--- | :---: |
| `TICK-201` | Programmatic MT5 Real Tick Ingestion (1–3 Bulan) | Deteksi simbol broker, fetch ticks via MT5 API dengan chunking per minggu/bulan, validasi kualitas, dan persist ke Parquet. | File Parquet partitioned di `data/parquet/xauusd/` | **DONE** |
| `TICK-202` | Market Microstructure & Spread Profiling (EDA) | Analisis distribusi spread per jam (UTC & WIB), tick velocity per sesi (London/NY/Asia), identifikasi zona blackout rollover. | `reports/microstructure_analysis.csv` & ringkasan console | **DONE** |
| `TICK-203` | Micro-Alpha Strategy Implementation | Membangun strategi scalping dengan session filter, dynamic spread gate, dan micro order flow imbalance. | `src/strategies/flow_momentum_scalper.py` + unit tests | **DONE** |
| `TICK-204` | In-Sample Backtesting & Cost Sensitivity Analysis | Backtest pada 70% data In-Sample riil dengan variasi stress-test latency (50ms vs 150ms vs 250ms) dan slippage. | Tear-sheet & laporan sensitivitas biaya | **DONE** |
| `TICK-205` | Out-of-Sample Walk-Forward Validation (WFA) | Uji buta pada 30% data Out-of-Sample riil untuk membuktikan ketahanan model terhadap overfitting. | WFA report & verifikasi kelolosan model | **DONE** |

---

## 3. Detail Spesifikasi Tiket

### `TICK-201`: Programmatic MT5 Real Tick Ingestion (1–3 Bulan)
* **Deskripsi:** Menghubungkan script Python ke terminal MT5 lokal (`C:\Program Files\MetaTrader 5\terminal64.exe`). Mengidentifikasi simbol yang tersedia di broker (misal: `XAUUSD`, `GOLD`, `XAUUSDm`, dll.), memeriksa spesifikasi simbol, dan menarik riwayat real tick 1–3 bulan terakhir menggunakan pembagian chunk mingguan agar tidak melebihi batasan memori buffer MT5. Data kemudian divalidasi dengan `TickDataValidator` dan disimpan terkompresi ke `data/parquet/`.
* **Input:** Koneksi MT5 lokal aktif.
* **Output:** Dataset Parquet partitioned di `data/parquet/xauusd/year=YYYY/month=MM/ticks.parquet`.
* **Acceptance Criteria (DoD):**
  - [ ] Terminal MT5 terdeteksi dan terhubung via `MetaTrader5.initialize()`.
  - [ ] Simbol gold broker terdeteksi otomatis (memeriksa `XAUUSD`, `GOLD`, dsb.).
  - [ ] Penarikan tick riil berhasil tanpa timeout/memori buffer overflow.
  - [ ] Validasi kualitas data: 0 invalid spread, urutan timestamp kronologis.
  - [ ] File tersimpan rapi di direktori Parquet.

### `TICK-202`: Market Microstructure & Spread Profiling (EDA)
* **Deskripsi:** Membangun modul analitik `src/analytics/microstructure.py` dan script `scripts/profile_market.py` untuk membedah data tick riil broker:
  1. *Spread Distribution per Jam:* Menghitung Mean, Median, Persentil 95th spread untuk setiap jam (00:00–23:00 UTC / 07:00–06:00 WIB).
  2. *Session Liquidity Window:* Mengklasifikasikan jam-jam likuiditas tinggi (London & NY overlap) dan jam rollover (spread melebar drastis).
  3. *Tick Arrival Velocity:* Menghitung rata-rata tick/detik per jam.
* **Input:** Dataset Parquet dari `TICK-201`.
* **Output:** Script profiling + tabel ringkasan + file `reports/microstructure_analysis.csv`.
* **Acceptance Criteria (DoD):**
  - [ ] Script `scripts/profile_market.py` berjalan mulus membaca Parquet riil.
  - [ ] Tabel jam trading optimal (*safe trading window*) dan jam rollover tercetak jelas.
  - [ ] Data profil diekspor ke CSV untuk referensi konfigurasi strategi.

### `TICK-203`: Micro-Alpha Strategy Implementation
* **Deskripsi:** Mengimplementasikan strategi `FlowMomentumScalper` di `src/strategies/flow_momentum_scalper.py` yang menggabungkan:
  1. *Trading Window Filter:* Hanya aktif pada jam likuiditas tinggi (sesuai hasil `TICK-202`).
  2. *Dynamic Spread Gate:* Menolak order jika spread saat itu melebihi batas toleransi broker.
  3. *Order Flow Velocity / Micro-Momentum:* Mengukur kecepatan dan arah tick delta dalam micro-window (misal 15–30 tick) dengan Stop Loss dan Take Profit ketat, serta time-stop (otomatis close jika posisi mengambang > N detik).
* **Input:** Hasil analisis `TICK-202` dan base strategy framework.
* **Output:** Modul strategi baru + unit test di `tests/test_flow_scalper.py`.
* **Acceptance Criteria (DoD):**
  - [ ] Filter jam dan spread berfungsi akurat.
  - [ ] Logika sinyal flow momentum teruji unit test.
  - [ ] 100% lulus pytest.

### `TICK-204`: In-Sample Backtesting & Cost Sensitivity Analysis
* **Deskripsi:** Menjalankan backtest pada 70% data pertama menggunakan `TickBacktestEngine`. Melakukan uji ketahanan terhadap biaya eksekusi (*cost sensitivity*) dengan memvariasikan:
  - Latency eksekusi: 50 ms vs 100 ms vs 200 ms.
  - Komisi broker: \$6/lot.
* **Input:** 70% In-Sample Parquet dataset.
* **Output:** Tear-sheet performa dan tabel sensitivitas biaya di console.
* **Acceptance Criteria (DoD):**
  - [ ] Backtest In-Sample selesai tanpa error.
  - [ ] Menampilkan metrik: Sharpe, Profit Factor, Win Rate, Max Drawdown net-of-costs.
  - [ ] Strategi mempertahankan edge positif setelah dipotong latency dan slippage.

### `TICK-205`: Out-of-Sample Walk-Forward Validation (WFA)
* **Deskripsi:** Menguji model final pada 30% data Out-of-Sample (data yang belum pernah dilihat model). Membandingkan rasio degradasi metrik $Sharpe_{OOS} / Sharpe_{IS}$ dan $PF_{OOS} / PF_{IS}$.
* **Input:** 30% Out-of-Sample Parquet dataset.
* **Output:** Laporan validasi Walk-Forward + Trade Log + Equity Curve.
* **Acceptance Criteria (DoD):**
  - [ ] Uji OOS berjalan secara blind/independen.
  - [ ] Status kelolosan anti-overfitting (PASS/FAIL) dilaporkan secara transparan.
  - [ ] File `reports/final_oos_trades.csv` dan `reports/final_oos_equity.csv` tersimpan.
