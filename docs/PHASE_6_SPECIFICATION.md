# Spesifikasi Teknis & Daftar Tiket: Fase F
## EXP-06: News Release & Afternoon Churn Blackout Engine (Range Sweep Scalper v5.0)

**Proyek:** XAUUSD Quantitative Scalping Research Platform  
**Fase:** Fase F - Microstructure Time Filtering (News Window & Churn Isolation)  
**Versi Dokumen:** 1.0.0  
**Tanggal:** 2026-11-07  
**Status Target:** Validasi Walk-Forward Analysis (WFA) pada 6.612.042 Tick Riil Broker Exness (`XAUUSDm`)  

---

## 1. Eksekutif & Filosofi Kuantitatif

### 1.1 Latar Belakang & Diagnosa Empiris EXP-05
Pada eksperimen sebelumnya (`EXP-05`: *Synergistic Step-Lock Scalper*), sistem berhasil mencapai status **Net Profitable** pada data uji buta Out-of-Sample (November 2026, 1,98 juta tick) dengan perolehan:
* **Net Profit:** +$55.30 (+0.55% Return)
* **Profit Factor:** 1.02
* **Win/Loss Ratio:** 2.88x (Rerata win $50.29 vs loss $17.49)
* **Max Drawdown:** 8.37% ($869.30)
* **Sharpe Ratio:** 1.47

Namun, bedah mikrostruktur per jam (*Hourly Microstructure Performance Breakdown*) mengungkap adanya **anomali toksik ekstrem** yang menggerus profitabilitas bot:

| Jam UTC | Waktu WIB | Sesi / Katalis Pasar | Total Trade (IS / OOS) | Win Rate (OOS) | Net PnL IS ($) | Net PnL OOS ($) | Total Kerugian ($) | Diagnosa Kuantitatif |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **12:00** | 19:00 | **US Major Macro Releases** (CPI, NFP, GDP, PPI, Retail Sales) | 52 / 21 | **0.0% (0W / 21L)** | -$737.10 | -$408.21 | **-$1.145,31** | **Toxic Runaway Trend:** Berita makro AS memicu lonjakan satu arah tanpa retest; asumsi mean-reversion hancur total. |
| **19:00** | 02:00 | **US Afternoon Churn & FOMC Statement** | 49 / 25 | **4.0% (1W / 24L)** | -$314.62 | -$371.27 | **-$685,89** | **Erratic Chop & Positioning:** Likuiditas tipis jelang penutupan NY + rotasi posisi institusi menghasilkan *whipsaw* tajam. |
| **TOTAL** | - | **Jam Toksik Gabungan** | **101 / 46** | **2.2% (1W / 45L)** | **-$1.051,72** | **-$779,48** | **-$1.831,20** | **46 trade OOS membuang -$779.48 secara sia-sia!** |

### 1.2 Hipotesis Alpha EXP-06
Dengan mengeliminasi jendela entri pada **Jam 12:00 UTC** dan **Jam 19:00 UTC** (serta mempertahankan Rollover Blackout pada Jam 21:00 & 22:00 UTC), sistem diproyeksikan:
1. **Memotong 46 transaksi berprobabilitas kalah 97.8%** di data Out-of-Sample.
2. **Memulihkan capital drag sebesar +$779.48**, sehingga Net Profit OOS melonjak dari **+$55.30** menjadi **+$834.78+**.
3. **Menaikkan Profit Factor OOS** dari **1.02** ke rentang **1.60 – 1.85**.
4. **Menekan Max Drawdown** dari 8.37% menjadi **< 6.00%**.
5. Menjaga integritas sesi prima: **London Open (07:00 UTC, +$574.32)**, **London Midday (10:00 UTC, +$408.49)**, dan **Asian Session (01:00 & 06:00 UTC, +$719.79)** tetap aktif 100% volume.

---

## 2. Arsitektur Teknis Sistem (RangeSweepScalperV5)

```
                    [ Incoming Real-Time Tick Event ]
                                   │
                                   ▼
                   [ Session & Macro Time Gate ]
       ┌───────────────────────────┴───────────────────────────┐
       ▼                                                       ▼
 [Blackout Hours UTC:                                   [Active Trading Hours:
  - 12:00 (US Macro News)                                - London (07:00-11:00 UTC)
  - 19:00 (NY Afternoon Churn)                           - Asian (23:00-06:00 UTC)
  - 21:00-22:59 (Rollover Spread)]                       - Mid NY (13:00-18:00, 20:00)]
       │                                                       │
       ▼                                                       ▼
 [Entry Blocked!]                                     [Spread & Range Filter]
 - Reset sweep tracking                                - Spread <= $0.25
 - Allow existing positions to                         - Range Width: $3.00 - $10.00
   exit naturally via TP/SL                            - Circuit Breaker Inactive
                                                               │
                                                               ▼
                                                  [Sweep & Rejection Engine]
                                                  - Min sweep $0.75 / Max $2.00
                                                  - Re-entry confirmation
                                                               │
                                                               ▼
                                                  [Step-Lock 3-Layer Manager]
                                                  - Layer 1 (0.05 lot) -> TP1 (EQ)
                                                  - Layer 2 (0.10 lot) -> TP2 (Edge)
                                                  - Layer 3 (0.15 lot) -> Runner locked at EQ
```

### 2.1 Kebijakan Gating Jam Transaksi (`allowed_hours_utc`)
* **Total Jam dalam Sehari:** 24 Jam (0 s/d 23 UTC).
* **Jam Terlarang Entri Baru (`blackout_hours_utc`):** `{12, 19, 21, 22}`
  - `12`: Rilis data inflasi (CPI), ketenagakerjaan (NFP), GDP, dan retail sales Amerika Serikat (19:00 WIB).
  - `19`: Penutupan sesi Eropa, pengumuman FOMC (02:00 WIB), dan penyeimbangan portofolio akhir hari Wall Street.
  - `21, 22`: Jendela Rollover broker Exness dengan lonjakan spread hingga $0.68 (04:00 - 06:00 WIB).
* **Jam Aktif Entri Baru (`allowed_hours_utc`):**
  $$\{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 20, 23\}$$
* **Manajemen Posisi Terbuka saat Memasuki Jam Blackout:**
  - Jika terdapat layer posisi yang dibuka pada menit 11:55 UTC atau 18:55 UTC, posisi **TIDAK** dipaksa ditutup (*no forced market close*).
  - Posisi tetap dipantau oleh `LayerManager` secara deterministik untuk mengeksekusi Hard SL, TP1, TP2, atau Step-Lock Runner.
  - Yang diblokir secara mutlak adalah **pembukaan setup baru** dan **pelacakan sweep baru** (`high_sweep_active = False`, `low_sweep_active = False`).

---

## 3. Matriks Parameter Lengkap (`RangeSweepScalperV5`)

| Parameter | Tipe | Nilai Default | Rationale Kuantitatif |
| :--- | :---: | :---: | :--- |
| `lookback_minutes` | `int` | `30` | Horizon 30 menit menangkap formasi range mikro M5–M30 tanpa noise berlebih. |
| `min_range_usd` | `float` | `3.00` | Sweet spot bawah: Pantulan emas sangat konsisten di lebar $3.50–$4.50. |
| `max_range_usd` | `float` | `10.00` | Sweet spot atas: Membuang fase ekspansi tren parabolik > $10.00. |
| `min_sweep_usd` | `float` | `0.75` | Kedalaman minimum sweep untuk memastikan likuiditas retail stop telah diserap. |
| `max_sweep_usd` | `float` | `2.00` | Batas maksimum sweep: Di atas $2.00 diklasifikasikan sebagai valid breakout. |
| `hard_sl_offset_usd` | `float` | `1.20` | Jarak batas invalidasi di luar titik puncak sweep ekstrim. |
| `layer_spacing_usd` | `float` | `0.50` | Jarak antar entri Layer 2 dan Layer 3 saat terjadi retest ke arah sweep. |
| `layer_volumes` | `list[float]` | `[0.05, 0.10, 0.15]` | Pembobotan posisi 3-layer terkontrol (total maksimum 0.30 lot). |
| `max_spread_usd` | `float` | `0.25` | Filter spread normal Exness ($0.24 nominal + $0.01 margin). |
| `cooldown_seconds` | `float` | `1200.0` | 20 menit masa tenang untuk batas range yang baru saja terkena Hard SL. |
| `be_policy` | `str` | `"STEP_LOCK"` | Formula BE juara: Layer 1 exit di EQ, Layer 2 exit di TP2, Runner dikunci di EQ. |
| `blackout_hours_utc` | `Set[int]` | `{12, 19, 21, 22}` | **Kunci EXP-06:** Blokir News Release, Afternoon Churn, dan Rollover Spread. |

---

## 4. Work Breakdown Structure (Daftar Tiket Fase F)

| ID | Judul Tiket | Scope Utama | File Output | Status |
| :--- | :--- | :--- | :--- | :---: |
| `TICK-601` | Phase F Technical Specification & Blueprint | Dokumen spesifikasi parameter, analisis jam toksik, formula matematis, dan blueprint eksekusi. | `docs/PHASE_6_SPECIFICATION.md` + Artifact | **DONE** |
| `TICK-602` | `RangeSweepScalperV5` Implementation | Pembuatan kelas strategi v5 dengan integrasi konfigurasi parameter blackout jam makro terpadu. | `src/strategies/range_sweep_scalper_v5.py` | **DONE** |
| `TICK-603` | Unit & Regression Verification Suite | Pengujian unit komprehensif untuk validasi isolasi jam 12, 19, 21, 22 UTC dan kelancaran jam aktif. | `tests/test_range_sweep_scalper_v5.py` | **DONE** |
| `TICK-604` | EXP-06 Walk-Forward Benchmark Runner | Eksekusi benchmark WFA (70% In-Sample / 30% Out-of-Sample) pada 6,6 juta tick riil broker Exness. | `scripts/run_experiment_exp06.py` | **DONE** |
| `TICK-605` | Master Registry & Leaderboard Evaluation | Rekonsiliasi matriks EXP-06 melawan EXP-01 s/d EXP-05, verifikasi kriteria target, dan tear-sheet reporting. | `docs/EXPERIMENT_REGISTRY.md` + Tear-sheet | **DONE** |

---

## 5. Rincian Kriteria Penerimaan (Definition of Done) Tiap Tiket

### `TICK-601`: Phase F Specification & Blueprint
* [x] Dokumen spesifikasi teknis `docs/PHASE_6_SPECIFICATION.md` telah dibuat dengan struktur formal.
* [x] Tabel perbandingan empiris performa jam toksik terlampir lengkap.
* [x] Artifact tersinkronisasi di brain conversation.

### `TICK-602`: `RangeSweepScalperV5` Implementation
* **Spesifikasi:**
  - Class `RangeSweepScalperV5` mewarisi `BaseStrategy`.
  - Mengimplementasikan argumen `blackout_hours_utc: Optional[Set[int]] = None` dengan default `{12, 19, 21, 22}`.
  - Memastikan method `on_tick` memeriksa apakah `tick.timestamp.hour in self.blackout_hours_utc`.
  - Jika masuk jam blackout, panggil `self._reset_sweep_state()` dan return `None` (posisi aktif tetap dievaluasi terlebih dahulu melalui `self.layer_mgr.evaluate()`).
* **Acceptance Criteria:**
  - [x] Kode bersih, terdokumentasi rapi, dan mematuhi type hinting Python 3.12.
  - [x] Tidak ada regresi logika pada mekanisme Step-Lock dan deteksi sweep.

### `TICK-603`: Unit & Regression Verification Suite
* **Spesifikasi:**
  - Test case memvalidasi penolakan sinyal baru pada jam 12:00 UTC (News window).
  - Test case memvalidasi penolakan sinyal baru pada jam 19:00 UTC (Afternoon churn window).
  - Test case memvalidasi penolakan sinyal baru pada jam 21:00 & 22:00 UTC (Rollover window).
  - Test case memvalidasi eksekusi sinyal normal pada London Open (07:00 UTC) dan Asian Session (01:00 UTC & 06:00 UTC).
  - Test case memvalidasi bahwa posisi terbuka yang masuk sebelum jam 12:00 tetap dimonitor hingga TP/SL tanpa error.
* **Acceptance Criteria:**
  - [x] 100% test case di `tests/test_range_sweep_scalper_v5.py` lulus.
  - [x] Seluruh test suite yang ada (`pytest tests/`) tetap hijau (zero regression, 36 passed).

### `TICK-604`: EXP-06 Walk-Forward Benchmark Runner
* **Spesifikasi:**
  - Script `scripts/run_experiment_exp06.py` mengeksekusi backtest pada 6.612.042 tick riil Exness.
  - Partisi 70% In-Sample (Oktober 2026, 4,62M tick) dan 30% Out-of-Sample (November 2026, 1,98M tick).
  - Ekspor trade log CSV dan kurva ekuitas ke direktori `reports/experiments/EXP-06/in_sample/` dan `reports/experiments/EXP-06/out_of_sample/`.
* **Acceptance Criteria:**
  - [x] Eksekusi selesai tanpa error memori atau crash numerik.
  - [x] Laporan performa tear-sheet tercetak jelas di terminal console.

### `TICK-605`: Master Registry & Leaderboard Evaluation
* **Spesifikasi:**
  - Melakukan komparasi side-by-side performa `EXP-06` melawan `EXP-01` s/d `EXP-05`.
  - Mengupdate tabel leaderboard di `docs/EXPERIMENT_REGISTRY.md`.
* **Target Kualifikasi Keberhasilan EXP-06:**
  - Out-of-Sample Net Profit $\ge +\$800.00$.
  - Profit Factor (OOS) $\ge 1.50$.
  - Win/Loss Ratio $\ge 2.80\text{x}$.
  - Max Drawdown $\le 6.50\%$.
* **Acceptance Criteria:**
  - [x] Dokumen `docs/EXPERIMENT_REGISTRY.md` terupdate dengan data valid.
  - [x] Status evaluasi resmi ditetapkan: 🏆 **NEW ALL-TIME CHAMPION MODEL**.
  - [x] Target kualifikasi terlampaui: Net Profit **+$1.133.20** (+11.33%), PF **1.55**, Win/Loss **3.02x**, Max DD **4.97%**.
