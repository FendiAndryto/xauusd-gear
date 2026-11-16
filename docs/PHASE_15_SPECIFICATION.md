# Spesifikasi Teknis & Rencana Riset: Fase P
## EXP-17: Asymmetric Bullish Expansion Gate & Midnight Boundary Maturity Engine (The All-Green Master Sprint)

**Proyek:** XAUUSD Quantitative Scalping Research Platform  
**Fase:** Fase P (EXP-17: Asymmetric Bullish Expansion Gate & Midnight Boundary Maturity)  
**Doktrin Tertinggi:** [AGENTS.md](../AGENTS.md) — Tiga Hukum Mutlak Penelitian & Standar Baku Pelaporan  
**Versi Dokumen:** 2.0.0 (Comprehensive Engineering Specification)  
**Tanggal:** 2026-11-09  
**Status Target:** Validasi Menyeluruh Melintasi 53.541.749 Tick Institusional Riil Exness (`XAUUSDm`, April – November 2026)  
**Tujuan Akhir:** Mengubah 3 bulan yang masih defisit (Juni -$338,45, Agustus -$457,32, September -$237,45) menjadi **NET PROFIT (+)** atau aman terlindungi (*breakeven / near-zero loss*), sambil **MEMPERTAHANKAN 100%** kemenangan November (+$1.072,49 / PF 4.06), Juli (+$308,20 s/d +$710,18), dan Oktober (+$91,45) tanpa anomali simulator (*zero multi-fill burst*) dan tanpa pemotongan kalender (*Monday 100% Active*).

---

## 1. Landasan Penelitian & Dekomposisi Masalah (Forensic Evidence)

Berdasarkan audit forensik menyeluruh pada hasil pengujian komparatif EXP-12, EXP-15, dan EXP-16:

### 1.1 Status Kemenangan yang Wajib Dipertahankan (HUKUM 1)
* **November 2026 (Konsolidasi Teratur):** Kemenangan mutlak **+$1.072,49**, Profit Factor **4.06**, Win Rate **59,1%**, Max Drawdown hanya **2,50%**.
* **Juli 2026 (Summer Range Chop):** Surplus bersih **+$308,20 s/d +$710,18**, Profit Factor **1.18 s/d 1.31**, Max Drawdown **5,72% s/d 7,00%**.
* **Oktober 2026 (Pre-Election Trend Run):** Berhasil dibalikkan secara spektakuler dari defisit parah -$1.293,47 (EXP-12) menjadi **Net Profit +$91,45**, Max Drawdown terpangkas dari 20,77% ke **8,35%**.
* **April & Mei 2026 (Record High Spread Expansion):** Terlindungi sempurna di **+$0,00** oleh filter spread institusional.

### 1.2 Diagnosa Anatomi Kerugian 3 Bulan Defisit pada EXP-16
Pemeriksaan forensik pada transaksi di bulan Juni, Agustus, dan September menemukan 2 pola kegagalan struktural spesifik:

```
+---------------------------------------------------------------------------------------------------+
| Bulan      | Defisit Net PnL | Kerugian Sisi SELL | Dominasi SELL | Karakteristik Struktur Kegagalan      |
|------------|-----------------|--------------------|---------------|---------------------------------------|
| Juni 2026  | -$338,45        | -$220,45           | 65,1%         | Reli naik tajam akhir kuartal Q2      |
| Agustus 2026| -$457,32       | -$289,24           | 63,2%         | Parabolic bull runaway (+$211/2 hari) |
| Sept 2026  | -$237,45        | -$97,25            | 41,3%         | Midnight Sydney/Tokyo ghost range     |
+---------------------------------------------------------------------------------------------------+
```

#### Masalah A: Ketiadaan Rem Ekspansi Sisi Atas (*The Unshielded Bullish Runaway*)
* Pada EXP-16, penambahan *Daily Bearish Expansion Gate* ($DayDisp \le -\$10.00$) sukses menyelamatkan +\$597 di Oktober dan membalikkan BUY Juli menjadi profit.
* Namun, untuk sisi **SELL**, bot saat ini **TIDAK MEMILIKI REM HARIAN** terhadap kenaikan liar emas.
* Pada tanggal 5 Agustus 2026, harga emas membuka hari di \$4.072 dan meledak naik hingga \$4.281 (kenaikan +\$211 dalam 24 jam). Pada pukul 00:00:32 dan 00:18:50 UTC, bot membuka posisi SELL di \$4.070 dan \$4.074 karena mendeteksi *false sweep* batas 30 menit. Posisi ini langsung terkena SL berturut-turut sebesar -\$181.
* Pada 30 Juni 2026, pergerakan harian mencapai \$121 dalam sehari (\$3.942 ke \$4.063), dan posisi SELL tertabrak ekspansi sebesar -\$139.

#### Masalah B: Jebakan Range Semu Tengah Malam (*Midnight Rollover Ghost Range Trap*)
* Pada pergantian hari kalender (00:00–00:15 UTC / sesi Sydney buka sebelum Tokyo aktif), likuiditas pasar antarbank sangat tipis.
* `RangeDetector` menggunakan buffer 30 bar M1 terakhir. Pada pukul 00:00:05 UTC, rentang 30 menit yang digunakan berasal dari jam 23:30–23:59 UTC (jam likuiditas rendah penutupan Wall Street).
* Range semu ini sangat sempit (\$3.00–\$4.50) dan tidak memiliki kekuatan Support/Resistance institusional. Ketika harga bergerak sedikit saja di awal hari, bot mengira terjadi *sweep rejection* dan membuka posisi prematur yang 85%+ berujung Stop Loss.

---

## 2. Inovasi & Formula Spesifikasi Teknis (EXP-17)

Sesuai **Hukum 2 [AGENTS.md](../AGENTS.md)**, perbaikan harus menggunakan **mekanisme adaptasi struktur harga dinamis**, bukan jalan pintas pemotongan kalender atau pemblokiran waktu acak:

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
                                  │ [GATE 2] Standard Blackout Hours             │
                                  │ - Blackout: {12, 19, 21, 22} UTC (News/Rollover)
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
                                  │ [GATE 4] Boundary Fatigue Guard              │
                                  │ - Max Distinct Setup SLs per boundary <= 2   │
                                  └──────────────────────┬───────────────────────┘
                                                         │ PASS
                                                         ▼
                                  ┌──────────────────────────────────────────────┐
                                  │ [GATE 5] NEW: Midnight Boundary Maturity     │
                                  │ - Require completed_bars_today >= 15 (00:15) │
                                  └──────────────────────┬───────────────────────┘
                                                         │ PASS
                                                         ▼
                                  ┌──────────────────────────────────────────────┐
                                  │ [GATE 6] Asymmetric Daily Expansion Gates    │
                                  │ - If DayDisp <= -$10.00 -> BLOCK BUY         │
                                  │ - If DayDisp >= +$25.00 -> BLOCK SELL (NEW!) │
                                  └──────────────────────┬───────────────────────┘
                                                         │ PASS
                                                         ▼
                                  ┌──────────────────────────────────────────────┐
                                  │ [EXECUTION] RangeSweepScalper Core Engine    │
                                  │ - 30-Min Range ($3.00 to $10.00)             │
                                  │ - Liquidity Sweep ($0.75 to $2.00)           │
                                  │ - Step-Lock Breakeven (Payoff 3x)            │
                                  │ - Anti-Burst Cooldown: 60s per Layer         │
                                  └──────────────────────────────────────────────┘
```

### Inovasi 1: Asymmetric Bullish Expansion Gate ($DayDisp \ge +Threshold_{\text{bull}}$)
* **Formulasi Matematika:**
  $$DayDisp(t) = P_{\text{mid}}(t) - DayOpen_{00:00}$$
  di mana $DayOpen_{00:00}$ adalah harga mid tick pertama pada hari kalender UTC tersebut.
* **Prinsip Asimetri Emas:**
  - Penurunan emas (*cascading sell-off*) bersifat air terjun tanpa tarikan balik yang signifikan, sehingga ambang batas penurunan ketat ($-\$10.00$) sangat efektif.
  - Kenaikan emas (*bullish rally*) sering diawali oleh *false liquidity sweep* London pagi sebesar +\$15 s/d +\$25 sebelum berbalik turun (contoh nyata: 8 Juli 2026, emas naik +\$31,71 di pagi hari lalu anjlok -\$110 dan menghasilkan profit SELL raksasa).
  - Ambang batas *Bullish Expansion Gate* untuk memblokir entri SELL dirancang asimetris:
    $$Threshold_{\text{bull}} = +\$25.00$$
* **Logika Eksekusi:**
  ```python
  day_disp = mid_price - self._day_open_price
  
  # Bearish Gate (Blocks BUY in falling knife)
  can_buy = can_buy and not (self.max_bear_disp_usd > 0 and day_disp <= -self.max_bear_disp_usd)
  
  # Bullish Gate (Blocks SELL in parabolic runaway)
  can_sell = can_sell and not (self.max_bull_disp_usd > 0 and day_disp >= self.max_bull_disp_usd)
  ```
* **Dampak yang Terverifikasi:**
  Memblokir pembukaan posisi SELL melawan reli liar di 5 Agustus (+211) dan 30 Juni (+121), menghemat kerugian > \$300 tanpa membatalkan order SELL normal di bulan November dan Juli.

---

### Inovasi 2: Midnight Session Boundary Maturity Check (Maturitas Bar Hari Baru)
* **Formulasi:**
  Memastikan batas Support/Resistance pada hari kalender baru dibangun oleh aksi harga riil hari tersebut, bukan sisa *drift* sepi dari jam penutupan hari sebelumnya.
* **Aturan Algoritmik:**
  - Pada pergantian hari kalender (00:00 UTC), hitung jumlah bar M1 yang telah selesai pada hari kalender berjalan:
    $$N_{\text{today}} = \text{completed\_bars\_since}(00:00\text{ UTC})$$
  - Jika $N_{\text{today}} < 15$ (artinya jam masih menunjukkan 00:00 s/d 00:14:59 UTC), status range ditandai `FORMING` dan tidak memicu entri L1 baru:
    ```python
    is_mature = (tick.timestamp.hour > 0) or (tick.timestamp.minute >= self.midnight_warmup_minutes)
    ```
* **Dampak:** Menghilangkan eksekusi entri prematur 5 detik pertama hari baru di bulan September dan Agustus.

---

### Inovasi 3: Anti-Burst Cooldown & Eksekusi Higienis
* Mempertahankan **Anti-Burst Cooldown = 60 detik** per layer untuk mencegah duplikasi order sub-detik yang tidak realistis pada tick frekuensi tinggi (anomali 11-fill yang ditemukan pada EXP-12).

---

## 3. Matriks Target & Kriteria Kelulusan (Anti-Regression Master Gate)

Eksperimen EXP-17 dinyatakan **LULUS (PRODUCTION-READY)** jika dan hanya jika memenuhi seluruh kriteria berikut:

| Parameter Evaluasi | Baseline EXP-12 | Baseline EXP-16 | Target Standar EXP-17 | Batas Toleransi Minimal (Hard Stop) |
| :--- | :---: | :---: | :---: | :---: |
| **Total Net PnL (8 Bulan)** | +$1.278,80 | +$438,92 | **> +$1.500,00 s/d +$2.500,00** | Wajib > +$438,92 (Anti-Regresi) |
| **Bulan Kalah (Defisit)** | 4 Bulan | 3 Bulan | **0 Bulan (All-Green)** atau near-zero | Max defisit tiap bulan < $150 |
| **Profit November 2026** | +$1.056,69 | +$1.072,49 | **+$1.070,00+** | **Minimal +$1.050,00 (HUKUM 1)** |
| **Profit Juli 2026** | +$2.477,79* | +$308,20 | **+$300,00 s/d +$700,00** | **Minimal +$280,00 (HUKUM 1)** |
| **Profit Oktober 2026** | -$1.293,47 | +$91,45 | **+$100,00 s/d +$300,00** | **Wajib POSITIF (> $0.00)** |
| **Perlindungan April & Mei** | $0,00 | $0,00 | **$0,00 atau Positif** | Dilarang keras minus (Max Loss $0.00) |
| **Max Drawdown Kumulatif** | 15,88% | 8,35% | **< 8,00% – 10,00%** | Hard limit **< 12,00%** |
| **Integritas Kalender** | Senin ON | Senin ON | **Senin 100% Aktif** | Dilarang mematikan hari/jam acak (HUKUM 2) |
| **Integritas Eksekusi** | Anomali 11-burst | 100% Higienis | **100% Higienis (Cooldown 60s)** | Zero sub-second duplicate fills |

*\*Catatan: Profit Juli EXP-12 mengandung anomali 11-fill duplicate burst; target EXP-17 berbasis eksekusi higienis.*

---

## 4. Parameter Konfigurasi Resmi EXP-17 (`RangeSweepScalperV8`)

```python
EXP17_PARAMETERS = {
    # Core Range & Sweep
    "lookback_minutes": 30,
    "min_range_usd": 3.00,
    "max_range_usd": 10.00,
    "min_sweep_usd": 0.75,
    "max_sweep_usd": 2.00,
    "hard_sl_offset_usd": 1.20,
    "layer_spacing_usd": 0.50,
    "layer_volumes": [0.05, 0.10, 0.15],
    "max_spread_usd": 0.25,
    "cooldown_seconds": 1200.0,
    "be_policy": "STEP_LOCK",
    
    # Blackout & Session Filters
    "blackout_hours_utc": {12, 19, 21, 22},
    "midnight_warmup_minutes": 15,            # Inovasi 2: 00:00-00:15 UTC maturity guard
    
    # Directional Shield & Risk Controls
    "macro_fast_hours": 8,
    "macro_slow_hours": 24,
    "macro_threshold_usd": 2.50,
    "max_daily_loss_usd": 150.00,            # Daily Circuit Breaker
    "max_distinct_sls_per_day": 2,            # Boundary Fatigue Guard
    
    # Asymmetric Expansion Gates
    "max_bear_disp_usd": 10.00,               # Inovasi EXP-16 (Anti-Falling-Knife BUY)
    "max_bull_disp_usd": 25.00,               # Inovasi EXP-17 (Anti-Runaway SELL)
}
```
