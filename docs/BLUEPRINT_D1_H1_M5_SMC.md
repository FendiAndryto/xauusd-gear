# BLUEPRINT: SISTEM MULTI-TIMEFRAME SMC (D1 - H1 - M5/M1) DENGAN ORDER BLOCK & RISK CIRCUIT BREAKER

Dokumen ini adalah **Piagam Spesifikasi & Target Acuan (Master Blueprint)** untuk metode trading baru berbasis *Smart Money Concepts (SMC)*, *Multi-Timeframe Structure*, dan *Order Block Integration* pada instrumen XAUUSD.

---

## 1. GOALS & TARGET MUTLAK (THE CORE CONSTRAINTS)

Agar riset dan pengembangan tidak melenceng (*ngawur ngalor-ngidul*), seluruh logika sistem wajib beroperasi di bawah batasan finansial berikut:

### A. Target Profit Harian (Daily Win Cap)
* **Target Maksimal:** **+10% per hari**.
* **Mekanisme Otomatis:** Seketika akumulasi realized profit harian mencapai target (+5% s/d +10%), sistem **WAJIB:**
  1. Menutup seluruh posisi aktif (market close all).
  2. Membatalkan seluruh pending order (cancel all).
  3. Mematikan eksekusi (*trading disabled / sleep mode*) hingga pergantian hari server (00:00 UTC / sesi hari berikutnya).
  4. Mengunci profit agar tidak tergerus *overtrading*.

### B. Batasan Risiko Harian (Daily Circuit Breaker / Max Drawdown)
* **Batas Maksimal Kerugian:** **-7.5% s/d -12.5% per hari** dari ekuitas awal hari (dinaikkan proporsional untuk mengakomodasi alokasi piramida 2.5% per setup, setara batas toleransi 3 s/d 5 setup loss beruntun).
* **Mekanisme Otomatis:** Jika terjadi kerugian beruntun mencapai batas ini, sistem **WAJIB:**
  1. Melakukan *hard close* seluruh posisi aktif.
  2. Membatalkan seluruh pending order.
  3. Menghentikan trading total untuk hari tersebut (*circuit breaker tripped*).
  4. Mencegah *revenge trading* dan melindungi modal dari anomali pasar/tren ekstrem.

### C. Rasio Risk-to-Reward & Eksekusi Harian
* **Risk Budget per Setup (Metode Piramida):**
  * **Layer 1 (Open OB / Tepi Luar):** Risiko **1.0%** ekuitas.
  * **Layer 2 (50% Mean Threshold OB):** Risiko **1.5%** ekuitas.
  * **Total Risiko Maksimal per Setup:** **2.5%** jika kedua order tereksekusi.
* **Minimum Target RR:** $1 : 2.0$ hingga $1 : 3.5+$.
* **Jumlah Trade per Hari:** **TIDAK DIBATASI** (bebas ambil setiap ada setup valid yang muncul, selama batasan harian Target Profit +10% atau Circuit Breaker -7.5% s/d -12.5% belum tersentuh).
* **Jam Operasional:** **24 Jam Non-Stop** (melintasi sesi Asia, London, dan New York guna evaluasi komprehensif struktur pasar).
* **Spread Guard:** Maksimal **$\le 3.5$ pips** ($35$ points). Jika spread melebihi batas ini (misal saat rollover 04.00-06.00 WIB atau lonjakan news), penempatan/eksekusi order ditahan (*freeze*).
* **Mode Eksekusi:** **Layered Pending Limit Order** pada zona Order Block (maksimal 2 - 3 entri per setup).
* **Stop Loss (SL):** Diletakkan di **pucuk ekor Sweep tertinggi/terendah (Extreme Sweep Wick)** $+ \text{buffer spread}$ Exness.
* **Mekanisme Take Profit (TP - Hybrid Structural):**
  * **TP 1:** Pada level *Equilibrium D1 (50% Range)* atau minimal $1 : 2.0$ RR $\rightarrow$ Tutup $50\%$ posisi, dan geser SL ke Breakeven (BEP / Risk-Free).
  * **TP 2 (Runner):** Target likuiditas struktural seberang (PDL untuk posisi SELL, atau PDH untuk posisi BUY) $\rightarrow$ Tutup sisa $50\%$ posisi.
* **Pembatalan Order (Cancellation Rule):** Pending order HANYA dibatalkan jika **struktur pasar rusak** (*Structural Invalidation / Opposite CHoCH*). Selama struktur masih valid, order tetap standby.

---

## 2. ARSITEKTUR MULTI-TIMEFRAME (MTF)

```
[ D1 ]  --> Penentuan Batas Likuiditas Eksternal (PDH / PDL / Equilibrium 50%)
  |
[ H1 ]  --> Penentu Arah Tren Utama & Order Flow (Bullish / Bearish Bias)
  |
[ M15 ] --> Transisi Struktur & Reaksi Level (Sweep vs Acceptance)
  |
[ M5 ]  --> Konfirmasi Perubahan Karakter (CHoCH) & Pemetaan ORDER BLOCK (OB)
  |
[ M1 ]  --> Eksekusi Sniper / Entry Mitigation di Area Order Block
```

---

## 3. DEFINISI & MEKANISME ORDER BLOCK (OB)

### A. Definisi Baku Order Block Institusional
* **Bullish Order Block (+OB):** Candle *bearish* terakhir sebelum terjadi gelombang dorongan (*displacement*) naik kencang yang berhasil menembus struktur resistance terdekat (*Bullish CHoCH/BOS*) serta meninggalkan ketidakseimbangan harga (*Fair Value Gap / FVG*).
* **Bearish Order Block (-OB):** Candle *bullish* terakhir sebelum terjadi gelombang dorongan (*displacement*) turun kencang yang berhasil menembus struktur support terdekat (*Bearish CHoCH/BOS*) serta meninggalkan FVG.

### B. Validasi Kualitas Order Block (Syarat Sah)
Sebuah Order Block hanya dianggap **VALID** untuk entri jika memenuhi 4 syarat:
1. **Menghasilkan Displacement:** Candle berikutnya wajib berbadan tebal (minimal $1.5\times$ ATR M5).
2. **Memecahkan Struktur:** Menyebabkan CHoCH atau BOS pada M5/M15.
3. **Meninggalkan Imbalance (FVG):** Terdapat celah harga antara High candle-1 dan Low candle-3.
4. **Masih Fresh (Unmitigated):** Harga belum pernah menyentuh kembali zona candle OB tersebut.

### C. Mekanisme Layered Entry pada Order Block (Maksimal 3 Order)
Untuk memaksimalkan *fill rate* sekaligus mengoptimalkan *average price*:
1. **Layer 1 (Open OB / Tepi Luar):** Dipasang tepat di harga Open candle Order Block (atau awal FVG). Menjamin bot tidak ketinggalan kereta jika harga hanya menyentuh permukaan zona.
2. **Layer 2 (Mean Threshold / 50% OB):** Dipasang di garis tengah (50% dari body/range candle Order Block). Memberikan rasio RR yang jauh lebih tajam.
3. **Layer 3 (Opsional Deep Retest - Max 3 Entri):** Jika zona OB cukup lebar, dipasang di area 75% kedalaman OB.
* **Aturan Alokasi Lot:** Total risiko dari seluruh layer jika terkena SL secara serentak **TIDAK BOLEH** melebihi alokasi *Risk Budget per Setup* (misal total gabungan tetap $1.5\%$ atau $2\%$).
* **Kesamaan SL:** Seluruh layer memiliki titik Stop Loss yang sama, yaitu di ujung ekor Sweep $+ \text{buffer spread}$.

---

## 4. INTEGRASI LEVEL D1, H1 BIAS, DAN ORDER BLOCK

### SKENARIO 1: SETUP REVERSAL (LIQUIDITY SWEEP + ORDER BLOCK)
1. **Trigger D1:** Harga menembus PDH (mencari *Buy-side Liquidity*) atau PDL (mencari *Sell-side Liquidity*).
2. **Reaksi M15:** Terjadi penolakan (*Rejection Wick* $\ge 50\%$ body).
3. **Konfirmasi M5:**
   * Terjadi **CHoCH** (penembusan struktur swing terdekat berlawanan arah).
   * Muncul **M5 Order Block** sebagai asal muasal dorongan CHoCH tersebut.
4. **Eksekusi:** Pasang Limit Order atau tunggu konfirmasi di zona **M5 Order Block**.
5. **Stop Loss:** Di atas titik tertinggi Sweep (+ buffer spread).
6. **Take Profit:** Target 1 di Equilibrium D1 (50% range), Target 2 di ujung Range D1 (PDL/PDH).

### SKENARIO 2: SETUP CONTINUATION (BREAKOUT ACCEPTANCE + BREAKER BLOCK)
1. **Trigger D1:** Harga menembus PDH/PDL dengan **Full Body Candle Close M15** di luar range.
2. **Validasi H1:** Arah H1 sejalan dengan arah penembusan (*Bullish bias* tembus PDH, atau *Bearish bias* tembus PDL).
3. **Zona Entry (Breaker Block / Order Block Flip):**
   * Order Block yang sebelumnya ditembus berubah fungsi menjadi area pantulan baru (*Support become Resistance / Resistance become Support*).
4. **Eksekusi:** Tunggu harga *retest* ke Breaker Block / OB baru di atas PDH (untuk BUY) atau di bawah PDL (untuk SELL).
5. **Stop Loss:** Di bawah zona Breaker Block / di bawah level PDH/PDL.
6. **Take Profit:** Target proyeksi ekstensi Fibonacci (1.272 atau 1.618 dari range harian).

---

## 5. PENANGANAN INSIDE DAY (D1 KEMARIN SIDEWAY)

* Jika candle D1 kemarin adalah **Inside Bar** (High kemarin < High 2 hari lalu, dan Low kemarin > Low 2 hari lalu):
  * Level acuan **DIBALIKKAN ke Mother Bar** (candle D1 sebelum Inside Bar terjadi).
  * Batas atas = High Mother Bar.
  * Batas bawah = Low Mother Bar.
  * Hal ini mencegah sistem terjebak di area *noise/chop* pasar yang sedang kompresi.

---

## 6. CEKLIST DISIPLIN SEBELUM EKSEKUSI (ENTRY GATEWAY)

Setiap entri WAJIB lolos 5 pintu filter:
- [ ] 1. Apakah Daily Cap (+10%) atau Daily Circuit Breaker (-7.5% s/d -12.5%) sudah tersentuh? (Jika YA $\rightarrow$ DILARANG TRADE).
- [ ] 2. Apakah lokasi harga berada di zona kritis (PDH, PDL, atau Equilibrium 50%)?
- [ ] 3. Apakah sudah ada konfirmasi CHoCH di timeframe eksekusi (bukan spekulasi mendahului)?
- [ ] 4. Apakah Order Block yang dituju berstatus *Fresh/Unmitigated* dengan *Imbalance*?
- [ ] 5. Apakah Rasio Risk-to-Reward terukur minimal $\ge 1 : 2.0$?
