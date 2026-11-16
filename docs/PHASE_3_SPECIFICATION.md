# Spesifikasi Teknis & Daftar Tiket: Fase C
## Range Boundary Liquidity Sweep & 3-Layer Mean-Reversion Scalper (XAUUSD)

**Proyek:** XAUUSD Quantitative Scalping Research Platform  
**Fase:** Fase C - Sideway Exploitation, False Breakout Traps & Controlled 3-Layer Execution  
**Versi Dokumen:** 1.0.0  
**Tanggal:** 2026-11-07  

---

## 1. Filosofi & Hipotesis Alpha

### 1.1 Premis Dasar
1. **Karakteristik Pasar Emas (XAUUSD):** Emas berada dalam kondisi konsolidasi/sideway sekitar 70%–80% dari waktu. Pada timeframe mikro (M5/M15), lebar area sideway berkisar antara **\$3.00 hingga \$8.00** (30–80 pip), yang memberikan ruang gerak sangat besar bagi scalper.
2. **Jebakan Retail (Liquidity Sweep & Fakeout):**
   * Di batas atas (*Range High* / $R_H$), retail memasang *Buy-Stop* (mengharapkan breakout) atau *Sell Stop Loss*.
   * Di batas bawah (*Range Low* / $R_L$), retail memasang *Sell-Stop* atau *Buy Stop Loss*.
   * Institusi dan market maker sering kali menyodok harga menembus level tersebut sejauh **\$0.40 – \$1.50** hanya untuk menyerap likuiditas order stop, lalu membalikkan arah harga (*reversal*) kembali ke dalam range.
3. **Mengapa Metode Ini Menguntungkan Secara Matematis?**
   * **Beban Biaya Rendah:** Target pantulan adalah garis tengah range (*Equilibrium* $E_Q = \$2.00 – \$3.50$) atau batas seberang (\$4.00 – \$7.00). Dengan spread broker \$0.24, beban biaya spread hanya memakan **5% – 9% dari total profit** (berbeda jauh dari scalping sub-detik yang memakan 32%).
   * **Rasio Risk-to-Reward (R:R) Tinggi:** Stop Loss diletakkan ketat \$1.00 di luar titik sweep ekstrim, menghasilkan rasio R:R minimal **1:2 hingga 1:3**.

---

## 2. Arsitektur Teknis Sistem

```
                 [News / Trend Circuit Breaker]
                                │ (Jika lolos)
                                ▼
               [Range Boundary Detector (M5/M15)]
                 - Plafon: Range High (RH)
                 - Garis Tengah: Equilibrium (EQ = 50%)
                 - Lantai: Range Low (RL)
                 - Filter Lebar: $3.00 <= Width <= $10.00
                                │
                                ▼
                 [Sweep & Rejection Trap Engine]
                 - Apakah harga menyapu RH/RL ($0.40 - $1.50)?
                 - Apakah harga gagal bertahan & cross back?
                                │ (Sinyal Terkonfirmasi)
                                ▼
                 [Controlled 3-Layer Manager]
                 - Layer 1 (0.05 lot): Masuk di konfirmasi reject
                 - Layer 2 (0.10 lot): Masuk jika ada pullback retest
                 - Layer 3 (0.15 lot): Masuk di zona ekstrim (Maks 3 Layer!)
                 - Shared Hard SL: $1.00 di luar sweep high/low (Cutloss semua!)
                                │
                                ▼
                 [Take Profit Management]
                 - TP 1: Garis Tengah Equilibrium (EQ, 50% posisi)
                 - TP 2: Batas Range Seberang (Trailing stop)
```

---

## 3. Work Breakdown Structure (Daftar Tiket Fase C)

| ID | Judul Tiket | Scope Utama | Output | Status |
| :--- | :--- | :--- | :--- | :---: |
| `TICK-301` | Range Boundary & Market Regime Detector | Modul pendeteksi sideway bergulir, filter lebar range (\$3–\$10), dan circuit breaker lonjakan volatilitas/berita. | `src/strategies/range_detector.py` + tests | **DONE** |
| `TICK-302` | Controlled 3-Layer Position Manager | Modul pengelola eksekusi bertingkat (Layer 1–3), shared invalidation stop loss bersama, dan split TP (50% EQ & opposite edge). | `src/simulator/layer_manager.py` + tests | **DONE** |
| `TICK-303` | Range Boundary Sweep Scalper Strategy | Integrasi strategi `RangeSweepScalper` ke framework `BaseStrategy` dengan parameter lengkap. | `src/strategies/range_sweep_scalper.py` + tests | **DONE** |
| `TICK-304` | In-Sample Backtest & Parameter Calibration | Backtest pada 70% real ticks MT5 (4,6 juta tick), kalibrasi threshold sweep, jarak layer, dan verifikasi net profit. | Laporan tear-sheet + trade log In-Sample | **DONE** |
| `TICK-305` | Out-of-Sample Walk-Forward Validation (WFA) | Uji buta pada 30% real ticks MT5 (1,98 juta tick) untuk memvalidasi apakah strategi lolos uji overfitting. | WFA report & status kelolosan | **DONE** |

---

## 4. Rincian Kriteria Penerimaan (DoD) Tiap Tiket

### `TICK-301`: Range Boundary & Market Regime Detector
* **Spesifikasi:**
  - Menghitung rolling Range High ($R_H$) dan Range Low ($R_L$) dari data tick/agregasi bar.
  - Memastikan kondisi sideway valid: Lebar range $R_H - R_L$ harus berada di antara **\$3.00 dan \$10.00**. Jika $< \$3.00$, range terlalu sempit/chop. Jika $> \$10.00$, pasar sedang dalam tren ekspansi/berita.
  - Menghitung garis tengah $E_Q = (R_H + R_L) / 2.0$.
  - Deteksi anomali kecepatan tick (*tick arrival spike*) untuk mematikan sinyal saat rilis berita.
* **Acceptance Criteria (DoD):**
  - [ ] Class `RangeDetector` terdefinisi dan mampu menghasilkan $R_H, R_L, E_Q$.
  - [ ] Filter lebar range (\$3–\$10) berfungsi akurat.
  - [ ] Circuit breaker memblokir deteksi saat terjadi volatilitas abnormal.
  - [ ] Unit test di `tests/test_range_detector.py` lulus 100%.

### `TICK-302`: Controlled 3-Layer Position Manager
* **Spesifikasi:**
  - Mengelola maksimal 3 layer per setup transaksi:
    - Layer 1: Bobot dasar (misal 0.05 lot).
    - Layer 2: Bobot retest (misal 0.10 lot, masuk jika harga retest $\sim \$0.40$ ke arah sweep).
    - Layer 3: Bobot ekstrim (misal 0.15 lot, masuk mendekati batas sweep).
  - **Shared Hard Invalidation SL:** Satu garis SL absolut yang berlaku untuk semua layer aktif. Jika harga menyentuh garis ini, seluruh layer dilikuidasi bersamaan.
  - **Dilarang Keras Layer ke-4:** Batas strict 3 posisi per setup untuk mencegah martingale.
  - **Dual TP Logic:** TP1 di level $E_Q$ (garis tengah), TP2 di level batas seberang.
* **Acceptance Criteria (DoD):**
  - [ ] Logika pembukaan Layer 1, 2, 3 tervalidasi.
  - [ ] Hard Invalidation memotong seluruh layer saat SL tersentuh.
  - [ ] Pembagian TP berfungsi akurat.
  - [ ] Unit test di `tests/test_layer_manager.py` lulus 100%.

### `TICK-303`: Range Boundary Sweep Scalper Strategy
* **Spesifikasi:**
  - Mengintegrasikan `RangeDetector` dan `LayerManager` ke dalam `src/strategies/range_sweep_scalper.py`.
  - Logika Bearish Sweep (SELL):
    - Harga menyentuh $R_H + \Delta_{sweep}$ ($\Delta_{sweep} \ge \$0.40$).
    - Terjadi penolakan (tick kembali turun melintasi $R_H$).
    - Pemicu sinyal Layer 1 SELL, setting Hard SL di $\text{Peak} + \$1.00$.
  - Logika Bullish Sweep (BUY):
    - Harga menyentuh $R_L - \Delta_{sweep}$ ($\Delta_{sweep} \ge \$0.40$).
    - Terjadi penolakan (tick kembali naik melintasi $R_L$).
    - Pemicu sinyal Layer 1 BUY, setting Hard SL di $\text{Low} - \$1.00$.
* **Acceptance Criteria (DoD):**
  - [ ] Strategi mewarisi `BaseStrategy` dan mengembalikan `OrderRequest` yang valid.
  - [ ] Unit test di `tests/test_range_sweep_scalper.py` lulus 100%.

### `TICK-304`: In-Sample Backtest & Parameter Calibration (Real Ticks)
* **Spesifikasi:**
  - Menjalankan simulasi pada 70% data real MT5 (4,6 juta tick).
  - Melakukan kalibrasi parameter:
    - Sweep penetration ($\$0.40$ s/d $\$0.80$).
    - Layer distance spacing.
    - TP target (Equilibrium vs Opposite Edge).
  - Menampilkan tear-sheet performa kuantitatif: Sharpe, Profit Factor, Win Rate, Expected Payoff, Max Drawdown.
* **Acceptance Criteria (DoD):**
  - [ ] Backtest selesai dengan output transaksi yang sehat (tidak overtrading puluhan ribu trade).
  - [ ] Net profit positif setelah memperhitungkan spread \$0.24 dan latensi eksekusi.
  - [ ] Hasil tear-sheet tercetak jelas dan diekspor ke CSV.

### `TICK-305`: Out-of-Sample Walk-Forward Validation (WFA)
* **Spesifikasi:**
  - Menguji parameter terbaik ke 30% data Out-of-Sample (November 2026, 1,98 juta tick).
  - Mengukur rasio degradasi performa $Sharpe_{OOS} / Sharpe_{IS}$ dan $PF_{OOS} / PF_{IS}$.
  - Menentukan status akhir validasi (PASS/FAIL).
* **Acceptance Criteria (DoD):**
  - [ ] Uji buta OOS selesai secara objektif.
  - [ ] Verifikasi ketahanan model terhadap overfitting.
  - [ ] Trade log final dan kurva ekuitas tersimpan di `reports/`.
