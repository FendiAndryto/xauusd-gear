# Spesifikasi Teknis & Daftar Tiket (WBS): Riset Scalping XAUUSD

**Proyek:** XAUUSD Tick-Level Scalping Research Platform  
**Target Komoditas:** Gold vs US Dollar (XAUUSD / Spot Gold)  
**Tingkat Granularitas:** Real Tick Data (Bid, Ask, Timestamp Milidetik/Nanodetik)  
**Bahasa & Core Engine:** Python 3.12, Polars, DuckDB, MetaTrader 5 API  
**Versi Dokumen:** 1.0.0  
**Tanggal:** 2026-11-07  

---

## 1. Executive Summary & Filosofi Desain

Tujuan dari sistem ini adalah membangun platform riset dan simulasi scalping berbasis data tick dengan presisi tinggi yang **menghilangkan bias "backtest palsu"** (overfitting dan unrealistic execution). 

Prinsip utama arsitektur ini:
1. **Realitas Eksekusi Di Atas Segalanya:** Tidak ada *fixed spread* dan tidak ada *zero-latency execution*. Setiap order harus tunduk pada selisih Bid/Ask riil, delay antrean eksekusi (50–150 ms), potensi slippage acak/volatilitas, dan komisi broker per lot round-turn.
2. **High-Throughput Storage & I/O:** Memproses puluhan juta baris tick per tahun menggunakan Apache Parquet terpartisi dan Polars, memangkas waktu load hingga >90% dibanding CSV konvensional.
3. **No Black-Box:** Menggunakan custom event-driven tick simulator berbasis Polars/Python agar seluruh perhitungan PnL, margin XAUUSD, dan eksekusi transparan serta dapat diaudit penuh.
4. **Validasi Kuantitatif Ketat:** Mengukur performa menggunakan metrik risiko (Sharpe, Sortino, Max Drawdown, Profit Factor) serta pengujian Out-of-Sample via Walk-Forward Analysis (WFA).

---

## 2. Arsitektur Sistem & Spesifikasi Modul

### 2.1 Spesifikasi Kontrak XAUUSD (Spesifikasi Broker)
* **Contract Size:** 100 troy ounces per 1.00 lot.
* **Digits / Precision:** 2 desimal (0.01) atau 3 desimal (0.001) tergantung broker.
* **Point Size:** $0.01 = 1 point (pada 2 digit) atau $0.001 (pada 3 digit). Pada XAUUSD standar, $0.10 gerakan harga per 1.00 lot bernilai \$10.00 USD ($1.00 gerakan per 1.00 lot bernilai \$100.00 USD).
* **Komisi Default:** \$6.00 per lot round-turn (\$3.00 open + \$3.00 close).
* **Leverage Default:** 1:100 (configurable hingga 1:500).

### 2.2 Schema Data Tick (Parquet)
| Kolom | Tipe Data | Deskripsi |
| :--- | :--- | :--- |
| `timestamp` | `Datetime[ns]` (UTC) | Waktu tick presisi milidetik/nanodetik |
| `bid` | `Float64` | Harga penawaran (harga jual trader) |
| `ask` | `Float64` | Harga permintaan (harga beli trader) |
| `flags` | `UInt32` | Flag MT5 (TICK_FLAG_BID, TICK_FLAG_ASK, dll.) |
| `volume` | `Float64` | Real/Tick volume dari feed broker |
| `spread` | `Float64` | Selisih `ask - bid` (dalam dollar/poin) |

Penyimpanan: File dipartisi dengan struktur direktori `data/parquet/year=YYYY/month=MM/xauusd_ticks.parquet` dengan kompresi ZSTD level 3.

### 2.3 Execution Reality Model (Cost & Delay Engine)
1. **Dynamic Spread:**
   * Order BUY dibuka di `Ask` dan ditutup di `Bid`.
   * Order SELL dibuka di `Bid` dan ditutup di `Ask`.
2. **Latency Queue:**
   * Ketika sinyal muncul pada timestamp $t_{signal}$, order masuk ke antrean tervalidasi pada $t_{exec} = t_{signal} + \Delta t_{latency}$.
   * $\Delta t_{latency}$ dimodelkan secara stokastik: $\mathcal{U}(\text{min\_ms}, \text{max\_ms})$ (default: 50ms – 150ms).
   * Harga eksekusi adalah harga tick pertama yang tersedia pada atau setelah $t_{exec}$.
3. **Slippage Model:**
   * Base slippage: Normal distribution $\mathcal{N}(\mu=0.01, \sigma=0.02)$ poin.
   * Volatility multiplier: Jika laju pergerakan harga ($\Delta price / \Delta t$) melampaui ambang persentil 95, slippage adverse meningkat secara proporsional.
4. **Komisi:**
   * Dikenakan seketika saat order ditutup: $\text{Commission} = \text{Lots} \times \text{CommissionPerLotRoundTurn}$.

### 2.4 Matriks Evaluasi & Validasi
* **Profit Factor (PF):** $\frac{\sum \text{Gross Profits}}{\sum |\text{Gross Losses}|}$ (Target: $> 1.50$ net of costs).
* **Sharpe Ratio (Annualized):** Mengukur excess return per unit volatilitas.
* **Sortino Ratio:** Hanya memperhitungkan downside semi-variance.
* **Maximum Drawdown (MDD):** Penurunan modal terdalam dari peak balance (dalam USD dan persentase).
* **Walk-Forward Analysis (WFA):** 70% In-Sample (IS) untuk deteksi parameter, 30% Out-of-Sample (OOS) untuk validasi buta. Rasio degradasi performa $\frac{Sharpe_{OOS}}{Sharpe_{IS}}$ harus $\ge 0.60$ agar strategi lolos uji overfitting.

---

## 3. Work Breakdown Structure (Daftar Tiket Pengerjaan)

### Phase 1: Environment & Project Foundation

#### `TICK-01`: Setup Python 3.12 Virtual Environment & Dependencies
* **Deskripsi:** Menginisialisasi virtual environment Python 3.12 terisolasi menggunakan `uv` di root workspace, mengonfigurasi dependensi inti (`polars`, `duckdb`, `pyarrow`, `MetaTrader5`, `scipy`, `pytest`).
* **Input:** Komputer host Windows dengan koneksi internet untuk dependency download.
* **Output:** Direktori `.venv`, file `pyproject.toml` / `requirements.txt`.
* **Acceptance Criteria (DoD):**
  - [ ] Virtual environment Python 3.12 aktif di `.venv`.
  - [ ] `import polars, duckdb, pyarrow, MetaTrader5, scipy` berhasil tanpa error.
  - [ ] Kompatibilitas library terverifikasi bebas konflik.

#### `TICK-02`: Project Directory Structure & Configuration Management
* **Deskripsi:** Membangun struktur direktori proyek standar dan modul konfigurasi terpusat (`src/config.py`).
* **Input:** Spesifikasi parameter broker (contract size, commission, spread limit).
* **Output:** Struktur folder `src/`, `data/`, `scripts/`, `tests/` dan modul `src/config.py`.
* **Acceptance Criteria (DoD):**
  - [ ] Direktori `data/raw`, `data/parquet`, `src/{ingestion,simulator,analytics,strategies}`, `tests/` terbentuk.
  - [ ] `src/config.py` memuat dataclass `BrokerConfig`, `ExecutionConfig`, dan `PathConfig` dengan default parameter XAUUSD.

---

### Phase 2: Data Ingestion & Storage Engine

#### `TICK-03`: MT5 Direct Tick Ingestion Module
* **Deskripsi:** Membangun modul Python `src/ingestion/mt5_collector.py` yang menginisialisasi koneksi ke terminal MT5 lokal (`terminal64.exe`), menarik real ticks untuk XAUUSD dalam rentang tanggal tertentu, dan mengubahnya menjadi Polars DataFrame.
* **Input:** Parameter rentang tanggal (start date, end date), simbol `XAUUSD`.
* **Output:** Polars DataFrame berisi data real ticks dari MT5.
* **Acceptance Criteria (DoD):**
  - [ ] Terhubung ke terminal MT5 aktif tanpa error.
  - [ ] Fungsi `fetch_ticks(symbol, start, end)` mampu mengambil chunk data per hari/bulan secara stabil.
  - [ ] Konversi timestamp MT5 ke UTC nanodetik akurat.

#### `TICK-04`: MT5 CSV History Importer Module
* **Deskripsi:** Membangun modul fallback `src/ingestion/csv_importer.py` untuk mengimpor file CSV hasil export manual dari History Center MT5 menggunakan streaming scanner Polars.
* **Input:** File CSV mentah di folder `data/raw/`.
* **Output:** Polars DataFrame terstandarisasi.
* **Acceptance Criteria (DoD):**
  - [ ] Membaca berbagai format delimiter CSV MT5 (tab-separated atau comma-separated).
  - [ ] Meng-handle parsing format tanggal dan waktu MT5 (`YYYY.MM.DD HH:MM:SS.mmm`).
  - [ ] Kecepatan parsing > 1.000.000 baris per detik via Polars.

#### `TICK-05`: Parquet Storage & Partitioning Manager
* **Deskripsi:** Membangun `src/ingestion/storage.py` untuk menyimpan data tick ke disk dalam format Apache Parquet dengan partisi `year=YYYY/month=MM/` serta menyediakan loader `load_ticks(symbol, start, end)`.
* **Input:** Polars DataFrame dari tick collector/importer.
* **Output:** File Parquet terkompresi ZSTD pada direktori `data/parquet/`.
* **Acceptance Criteria (DoD):**
  - [ ] File tersimpan rapi per partisi tahun dan bulan.
  - [ ] Deduplikasi data berdasarkan timestamp unik.
  - [ ] Fungsi `load_ticks()` mendukung lazy loading via `polars.scan_parquet()` dengan filter waktu instan.

#### `TICK-06`: Data Quality & Integrity Checker
* **Deskripsi:** Membangun utilitas `src/ingestion/validator.py` untuk memeriksa kualitas data tick sebelum dipakai riset.
* **Input:** File Parquet ticks.
* **Output:** Laporan integritas data (anomali log).
* **Acceptance Criteria (DoD):**
  - [ ] Mendeteksi adanya `Ask <= Bid` (negative / zero spread anomaly).
  - [ ] Mendeteksi timestamp mundur / out-of-order.
  - [ ] Mendeteksi outlier harga ekstrim (bad tick spike akibat feed error).

---

### Phase 3: Reality Simulator (Cost, Latency & Execution Engine)

#### `TICK-07`: Account & Position State Tracker
* **Deskripsi:** Membangun `src/simulator/portfolio.py` yang melacak saldo kas, ekuitas mengambang, margin yang digunakan, dan riwayat posisi terbuka/tertutup.
* **Input:** Transaksi beli/jual, update harga tick berjalan.
* **Output:** Object state akun yang ter-update secara real-time.
* **Acceptance Criteria (DoD):**
  - [ ] Kalkulasi margin akurat untuk contract size 100 oz XAUUSD.
  - [ ] Kalkulasi Floating PnL akurat per tick: $(Bid - OpenAsk) \times 100 \times Lots$ untuk Buy, $(OpenBid - Ask) \times 100 \times Lots$ untuk Sell.
  - [ ] Margin Call / Stop Out trigger jika Margin Level $\le$ threshold broker (misal 50%).

#### `TICK-08`: Execution Reality Model (Spread, Latency, Slippage, Fees)
* **Deskripsi:** Membangun `src/simulator/execution.py` yang memodelkan realitas eksekusi order scalper.
* **Input:** Order request (Buy/Sell/Close), waktu sinyal $t_{signal}$, tick feed.
* **Output:** Filled order object dengan harga eksekusi final, waktu eksekusi riil, slippage, dan komisi.
* **Acceptance Criteria (DoD):**
  - [ ] Buy selalu terisi di `Ask + Slippage`, Sell di `Bid - Slippage`.
  - [ ] Latency buffer menunda eksekusi order minimal $\Delta t$ ms ke tick berikutnya.
  - [ ] Komisi otomatis terpotong saat penutupan posisi.

#### `TICK-09`: Core Tick Event-Driven Simulator Engine
* **Deskripsi:** Membangun `src/simulator/engine.py` yang memutar data tick secara kronologis dan mengevaluasi status Stop Loss (SL), Take Profit (TP), trailing stop, serta sinyal strategi.
* **Input:** Lazy scan Polars DataFrame, instance strategi, parameter eksekusi.
* **Output:** Trade Log lengkap (daftar semua transaksi tertutup) dan Equity Curve time-series.
* **Acceptance Criteria (DoD):**
  - [ ] Evaluasi trigger SL/TP dilakukan pada level tick (bukan high/low candle M1).
  - [ ] Urutan kejadian logis terjamin (tidak ada look-ahead bias).
  - [ ] Efisiensi eksekusi tinggi (mampu memproses ratusan ribu tick dalam beberapa detik).

---

### Phase 4: Statistical Analytics & Validation Framework

#### `TICK-10`: Quantitative Performance & Risk Metrics
* **Deskripsi:** Membangun `src/analytics/metrics.py` untuk menghitung metrik kuantitatif lengkap dari Trade Log dan Equity Curve.
* **Input:** List of executed trades dan equity time-series.
* **Output:** Dataclass `BacktestReport` berisi metrik statistik.
* **Acceptance Criteria (DoD):**
  - [ ] Menghitung: Total Return, Win Rate, Profit Factor, Expected Payoff, Sharpe Ratio, Sortino Ratio, Max Drawdown (USD & %), Average Trade Duration.
  - [ ] Perhitungan formula terverifikasi dengan unit test matematis.

#### `TICK-11`: Walk-Forward Analysis (WFA) Engine
* **Deskripsi:** Membangun `src/analytics/validation.py` untuk mengotomasi pengujian out-of-sample rolling window guna mendeteksi overfitting strategi.
* **Input:** Dataset tick lengkap, parameter pembagian in-sample vs out-of-sample (e.g. 70/30).
* **Output:** Laporan rasio degradasi performa In-Sample vs Out-of-Sample.
* **Acceptance Criteria (DoD):**
  - [ ] Memisahkan data tanpa data leakage.
  - [ ] Mengeluarkan rasio OOS/IS untuk Sharpe, Profit Factor, dan Win Rate.

#### `TICK-12`: Reporting & Visualization Generator
* **Deskripsi:** Membangun `src/analytics/reporting.py` untuk menampilkan tabel ringkasan performa di terminal console dan mengekspor Trade Log ke CSV / Parquet untuk audit mendalam.
* **Input:** `BacktestReport` object.
* **Output:** Output console terformat dan file laporan tersimpan.
* **Acceptance Criteria (DoD):**
  - [ ] Menampilkan ringkasan metrik eksekutif di console yang mudah dibaca.
  - [ ] Menyimpan `trades_summary.csv` dan `equity_curve.csv` di folder `reports/`.

---

### Phase 5: Baseline Strategy & End-to-End Prototype Validation

#### `TICK-13`: Strategy Interface & Baseline Benchmark Strategy
* **Deskripsi:** Membangun `src/strategies/base.py` (abstract class) dan satu strategi acuan sederhana `src/strategies/micro_momentum.py` (misal: Tick Imbalance / Volatility Breakout) untuk menguji seluruh pipeline.
* **Input:** Interface strategi dan data tick.
* **Output:** Sinyal trading (BUY, SELL, HOLD, CLOSE).
* **Acceptance Criteria (DoD):**
  - [ ] Class `BaseStrategy` terdefinisi dengan method `on_tick(tick)` yang modular.
  - [ ] Strategi benchmark menghasilkan sinyal trading yang valid saat dialiri tick.

#### `TICK-14`: End-to-End Pipeline Integration Test
* **Deskripsi:** Membuat script runner utama `scripts/run_pipeline.py` yang mengintegrasikan ingestion sampel 1–3 bulan data, penyimpanan Parquet, eksekusi backtest dengan simulator realita, hingga laporan metrik akhir.
* **Input:** Data tick XAUUSD sampel 1–3 bulan dari MT5.
* **Output:** Hasil backtest lengkap dari hulu ke hilir.
* **Acceptance Criteria (DoD):**
  - [ ] Pipeline berjalan mulus dari ingestion -> parquet -> simulator -> metrics tanpa crash.
  - [ ] Seluruh komponen biaya (spread, slippage, komisi) tercermin dalam PnL.

---

## 4. Urutan Pengerjaan yang Dianjurkan (Dependency Graph)

```
[TICK-01: Python 3.12 Env] ──> [TICK-02: Project & Config]
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
     [TICK-03: MT5 Collector]                        [TICK-04: CSV Importer]
                 │                                               │
                 └───────────────────────┬───────────────────────┘
                                         ▼
                             [TICK-05: Parquet Storage]
                                         │
                                         ▼
                            [TICK-06: Data Validator]
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
     [TICK-07: Portfolio Tracker]                    [TICK-08: Execution Reality]
                 │                                               │
                 └───────────────────────┬───────────────────────┘
                                         ▼
                              [TICK-09: Core Simulator Engine]
                                         │
                                         ▼
                              [TICK-10: Metrics Calculator]
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
     [TICK-11: Walk-Forward Engine]                  [TICK-12: Reporting]
                 │                                               │
                 └───────────────────────┬───────────────────────┘
                                         ▼
                             [TICK-13: Baseline Strategy]
                                         │
                                         ▼
                             [TICK-14: E2E Integration Test]
```

---

## 5. Ringkasan Status Tiket

| ID | Tiket | Estimasi Urutan | Status |
| :--- | :--- | :--- | :--- |
| `TICK-01` | Setup Python 3.12 venv & Dependencies | Tahap 1 | **DONE** |
| `TICK-02` | Project Structure & Config Management | Tahap 1 | **DONE** |
| `TICK-03` | MT5 Direct Tick Collector | Tahap 2 | **DONE** |
| `TICK-04` | MT5 CSV Importer | Tahap 2 | **DONE** |
| `TICK-05` | Parquet Storage & Partitioning | Tahap 2 | **DONE** |
| `TICK-06` | Data Quality & Integrity Checker | Tahap 2 | **DONE** |
| `TICK-07` | Portfolio & Margin Tracker | Tahap 3 | **DONE** |
| `TICK-08` | Execution Reality Model (Cost & Delay) | Tahap 3 | **DONE** |
| `TICK-09` | Core Tick Simulator Engine | Tahap 3 | **DONE** |
| `TICK-10` | Quantitative Performance Metrics | Tahap 4 | **DONE** |
| `TICK-11` | Walk-Forward Analysis Engine | Tahap 4 | **DONE** |
| `TICK-12` | Reporting & Tear-sheet Generator | Tahap 4 | **DONE** |
| `TICK-13` | Strategy Interface & Benchmark | Tahap 5 | **DONE** |
| `TICK-14` | E2E Pipeline Integration Test | Tahap 5 | **DONE** |
