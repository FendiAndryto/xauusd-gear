# SPESIFIKASI REKAYASA TEKNIS
## Dedicated Pure Price Action Replay & Simulator Suite (XAUUSD M5, M15, H1)

**Dokumen ID:** `SPEC-PA-REPLAY-01`  
**Status:** APPROVED / READY FOR IMPLEMENTATION  
**Kategori:** Web Visual Testing, Simulation & Price Action Training Engine  
**Target Platform:** Web Assistant Dashboard (`src/assistant/`)  
**Doktrin Tertinggi:** [`AGENTS.md`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/AGENTS.md)

---

## 1. Latar Belakang & Visi Produk (Product Vision)

Sistem asisten scalping XAUUSD ditransformasi secara terarah dari aplikasi hibrida (*hybrid live assistant + bot signal scanner*) menjadi **Dedicated Pure Price Action Replay Terminal**. 

### Mengapa Pure Price Action Tanpa Marker Bot?
1. **Fokus Latihan Kognitif & Intuisi Pasar:**
   Trader memerlukan lingkungan latihan visual murni tanpa distraksi visual (*zero clutter*). Penanda grafis otomatis dari bot (panah sinyal BUY/SELL, garis TP/SL otomatis, dan arsiran zona bot) dihilangkan agar trader dapat melatih identifikasi struktur pasar riil (*Market Structure, Liquidity Sweeps, Order Blocks, Rejection, FVG*) secara objektif.
2. **Kualitas Interaksi Setara TradingView:**
   Pengalaman memutar lilin historis harus memiliki fleksibilitas penuh:
   - Navigasi maju/mundur batang demi batang (*bar-by-bar*).
   - Kemampuan *pan/drag* bebas saat di-pause untuk menganalisis riwayat ke belakang.
   - Kemampuan *zoom in / zoom out* dinamis kapan saja tanpa terinterupsi saat replay sedang berjalan (*auto-follow* ujung kanan lilin).
   - Mode layar penuh (*fullscreen*) satu klik untuk fokus maksimal.
3. **Arsitektur Ramping & Bebas Dead Code:**
   Seluruh modul dan dependensi pemrosesan sinyal live (WebSocket broadcaster, loop live streaming, SQLite live journal, generator narasi setup) dipangkas bersih. Koneksi MT5 tetap dipertahankan sebagai utilitas status broker dan ingestion data.

---

## 2. Arsitektur Sistem Baru (New System Architecture)

```
+-----------------------------------------------------------------------------------+
| METATRADER 5 TERMINAL (Broker Server / Exness)                                    |
| Status: Terhubung via MT5Bridge (Status monitor & historical bar copy)            |
+-----------------------------------------------------------------------------------+
                                       │
                                       │ scripts/download_history_10y.py
                                       ▼
+-----------------------------------------------------------------------------------+
| DATA STORAGE (Local Parquet Cache) `data/cache_bars/`                             |
| 179 file bulanan, 528.207 bar, 16,76 MB (audit 2026-11-16):                       |
|   - H1:  h1_YYYY_MM.parquet   101 file,  32.718 bar, 2018-07 s/d 2026-11        |
|   - M15: m15_YYYY_MM.parquet   49 file,  94.942 bar, 2022-11 s/d 2026-11        |
|   - M5:  m5_YYYY_MM.parquet    18 file,  98.670 bar, 2025-06 s/d 2026-11        |
|   - M1:  m1_YYYY_MM.parquet    11 file, 301.877 bar, 2026-01 s/d 2026-11        |
+-----------------------------------------------------------------------------------+
                                       │
                                       │ Fast metadata scan & parquet read
                                       ▼
+-----------------------------------------------------------------------------------+
| BACKEND API (FastAPI) `src/assistant/app.py` & `replay_api.py`                    |
|   - GET /api/mt5/status, connect, disconnect (MT5 cluster)                        |
|   - GET /api/replay/sessions (Katalog periode dinamis & deteksi timeframe)        |
|   - GET /api/replay/data (Candle batch murni berdasarkan periode + timeframe)     |
+-----------------------------------------------------------------------------------+
                                       │
                                       │ JSON HTTP (Single payload per session)
                                       ▼
+-----------------------------------------------------------------------------------+
| FRONTEND SUITE (Lightweight Charts + Pure JS) `src/assistant/static/`              |
|                                                                                   |
|  1. Period & Timeframe Selector (Bulan, Rentang Bulan, Tahun, Custom + M5/M15/H1) |
|  2. Replay Clock & State Machine (STOPPED, PLAYING, PAUSED, STEPPING, COMPLETED)  |
|  3. TradingView-Grade Incremental Renderer (Smart Follow + Free Zoom/Pan)         |
|  4. Fullscreen Canvas Manager (Native Fullscreen API + Shortcut 'F')              |
|  5. Floating Minimal HUD (Waktu Bar UTC/Lokal, Harga Terkini, Status Bar)        |
+-----------------------------------------------------------------------------------+
```

---

## 3. Spesifikasi Pipeline Data Historis (Cakupan Aktual per Timeframe)

> **Koreksi 2026-11-16 (audit T-PAR-02).** Bagian ini sebelumnya mengklaim
> "10 Tahun Penuh" (2017-01-01 s/d 2026-11-16) untuk semua timeframe. Klaim itu
> tidak pernah benar: server broker tidak menyediakan bar sedalam itu. Angka di
> bawah adalah hasil `scripts/verify_parquet_cache.py` terhadap 179 file nyata di
> `data/cache_bars/`.

### 3.1. Spesifikasi Penarikan Data
* **Rentang yang diminta:** 1 Januari 2017 s/d 16 November 2026, diminta per bulan.
* **Rentang yang benar-benar tersedia** (batas server broker, bukan bug ingest):

  | Timeframe | Awal tersedia | Akhir tersedia | File | Total bar |
  | :--- | :--- | :--- | ---: | ---: |
  | H1  | 2018-07-01 | 2026-11-13 | 101 | 32.718 |
  | M15 | 2022-11-01 | 2026-11-06 | 49  | 94.942 |
  | M5  | 2025-06-18 | 2026-11-06 | 18  | 98.670 |
  | M1  | 2026-01-01 | 2026-11-06 | 11  | 301.877 |

  Total 528.207 bar / 16,76 MB. **H1 adalah satu-satunya timeframe yang mendekati
  satu dekade, dan itu pun mulai Juli 2018 — bukan 2017.** M5 hanya mencakup
  ~17 bulan. Setiap laporan yang menyebut "10 tahun M5/M15" adalah salah dan
  harus dikoreksi.
* **Format Waktu Awal:** Tanggal 1 Januari pukul 00:00:00 UTC di setiap tahun.
* **Instrumen:** Simbol XAUUSD broker aktif (otomatis mendeteksi `XAUUSD`, `XAUUSDm`, dll).
* **Timeframe:** `mt5.TIMEFRAME_H1`, `mt5.TIMEFRAME_M15`, `mt5.TIMEFRAME_M5`
  (ditambah `M1` untuk verifikasi agregasi tick).


### 3.2. Penanganan Limitasi Broker & Auto-Fallback
* Pengaturan terminal MT5: User telah mengonfigurasi `Max bars in chart = Unlimited`.
* Skrip `download_history_10y.py` melakukan download secara modular per bulan.
* Jika server broker membatasi riwayat M5 pada tahun-tahun lama (misal data M5 di server broker hanya tersedia mulai tahun 2020), skrip mencatat log informasi tanpa menghentikan proses (*graceful degrade*), menandai rentang M5 yang valid, dan tetap menyelesaikan H1 serta M15 sedalam yang tersedia.
  Hasil nyata: H1 mulai 2018-07, M15 mulai 2022-11, M5 mulai 2025-06. Permintaan
  ke 2017 dijawab broker dengan array kosong, dan itu **bukan** kondisi error.

### 3.3. Skema Parquet Standar
Setiap file parquet menyimpan bar dengan skema terstandardisasi:

* `time`: Int64 (Epoch seconds UTC)
* `open`: Float64 — presisi sumber dipertahankan
* `high`: Float64 — presisi sumber dipertahankan
* `low`: Float64 — presisi sumber dipertahankan
* `close`: Float64 — presisi sumber dipertahankan
* `tick_volume`: UInt64 (jumlah tick riil dalam bar)
* `spread`: Int32 (spread rata-rata dalam point; 1 point = 0,001)
* `real_volume`: UInt64 (0 untuk bar turunan tick)
* `timestamp`: Datetime naive UTC (`us` dari downloader MT5, `ns` dari resampler tick —
  keduanya dinormalisasi oleh `replay_engine._load_bar_pair`)

**Presisi harga — penting.** Spesifikasi lama mewajibkan "2 desimal" untuk OHLC.
Itu salah dan berbahaya: symbol ini punya `point = 0,001`, dan bar yang diagregasi
dari tick parquet membawa 3 desimal (mis. `4151.117`). Pembulatan ke 2 desimal
menggeser harga ratusan dolar per bulan dan **memutus paritas benchmark**
(Oktober 2026: 48 trade / +23,5% / WR 56,25%). Karena itu OHLC **tidak pernah**
dibulatkan; skrip repair hanya memastikan tipe datanya `Float64`.

**Dua produsen, satu kontrak.**

| Produsen | Sumber | Konsekuensi |
| :--- | :--- | :--- |
| `scripts/download_history_10y.py` | `mt5.copy_rates_range()` | Sudah lengkap: OHLC + `tick_volume` + `spread` + `real_volume` |
| `scripts/prepare_months_01_02_03.py` | agregasi `data/parquet/xauusd/year=*/month=*/ticks.parquet` | Hanya OHLC mid-price; volume/spread harus direkonstruksi dari tick yang sama |

File dari produsen kedua tidak boleh diunduh ulang dengan `copy_rates_range()`:
harga mid-price dan harga rate berbeda setengah spread (~+0,12), sehingga
re-download akan memecah paritas. Gunakan
`scripts/repair_bar_cache_schema.py`, yang mengembalikan kolom metadata dari tick
sumber dan **memverifikasi OHLC tidak bergeser sebelum menulis**.


---

## 4. Pembersihan Kode Sinyal (Signal Dead Code Elimination)

Semua modul yang berhubungan eksklusif dengan sinyal otomatis bot dan live streaming dihapus secara permanen:

> **Koreksi 2026-11-16.** Tabel lama mencantumkan `analyzer.py` dan `setups.py`, dua file
> yang **tidak pernah ada** di repositori ini. Fungsinya sudah lama menyatu di
> `smc_live.py` (analisis SMC live) dan `setup_state.py` (state machine setup), dan
> keduanya hanya dipakai oleh `streamer.py`. Karena itu keduanya juga ikut dihapus —
> kalau tidak, menghapus `reasoning.py` saja akan meninggalkan broken import.

| File / Modul | Alasan Penghapusan | Dampak |
| :--- | :--- | :--- |
| `src/assistant/streamer.py` | Polling live tick MT5 & WebSocket broadcaster tidak lagi dipakai | CPU idle saat web terbuka, memori bebas |
| `src/assistant/smc_live.py` | Analisis SMC live (swing/CHoCH/order block real-time) — pengganti `analyzer.py` yang disebut tabel lama | Mengeliminasi beban kalkulasi background |
| `src/assistant/setup_state.py` | State machine setup live — pengganti `setups.py` yang disebut tabel lama; hanya dipakai `streamer.py` | Menghapus dead code sinyal bot |
| `src/assistant/journal.py` | SQLite live tracking journal T-11/T-12 | Menghilangkan persistensi database SQLite live |
| `src/assistant/reasoning.py` | Generator teks narasi sinyal bot; satu-satunya pemakainya `setup_state.py` | Menghapus dependensi teks sinyal |
| `src/assistant/static/js/stream.js` | WebSocket client handler di browser | Menghilangkan koneksi WS yang tidak dibutuhkan |
| `src/assistant/static/js/setups.js` | UI rendering kartu sinyal aktif | Komponen HTML kartu setup dihilangkan |
| `src/assistant/static/js/evaluation.js` | UI rendering riwayat evaluasi performa live | Tab evaluasi dihilangkan |
| `src/assistant/static/js/chart.js` | Live chart lama untuk MT5 stream | Digantikan sepenuhnya oleh `replay_chart.js` |
| `src/assistant/static/js/overlay.js` | Visualizer gambar overlay live SMC | Menghapus render grafis sinyal lama |
| `tests/test_assistant_journal.py`, `tests/test_assistant_setup_state.py` | Menguji modul yang dihapus | −25 test; sisa 100 test lulus |

---

## 5. Kontrak Data & Spesifikasi API Backend

### 5.1. Endpoint: `GET /api/replay/sessions` & `GET /api/replay/coverage`
Mengembalikan katalog ketersediaan data berdasarkan hasil pindai metadata parquet (tanpa mendecode seluruh bar; 179 footer ≈ 0.5 s cold, di-cache terhadap mtime direktori sehingga panggilan berikutnya $< 50$ ms).

`sessions` mengembalikan kunci lama (paritas benchmark: `sessions`, `default_session_id`, `strategies`, `rr_presets`) **plus** blok katalog di bawah. `coverage` hanya mengembalikan blok katalog.

**Response Schema:**
```json
{
  "available_years": [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026],
  "timeframes": ["M5", "M15", "H1", "M1"],
  "period_modes": ["month", "year", "multi_month", "custom", "all"],
  "timeframe_coverage": {
    "M5": {
      "start_date": "2025-06-01",
      "end_date": "2026-11-06",
      "usable_start_date": "2025-06-01",
      "total_bars": 98670,
      "months": 18,
      "median_bars": 5915,
      "years": [2025, 2026],
      "sparse_months": ["2026-11"]
    }
  },
  "default_selection": {
    "period_mode": "month",
    "year": 2026,
    "month": 10,
    "timeframe": "M5"
  }
}
```

**Cakupan nyata per 2026-11-16** (dihasilkan `GET /api/replay/coverage`):

| TF | `start_date` | `usable_start_date` | `end_date` | `total_bars` | bulan | `median_bars` | `sparse_months` |
| :--- | :--- | :--- | :--- | ---: | ---: | ---: | ---: |
| M5 | 2025-06-01 | 2025-06-01 | 2026-11-06 | 98.670 | 18 | 5.915 | 1 |
| M15 | 2022-11-01 | 2022-11-01 | 2026-11-06 | 94.942 | 49 | 1.940 | 1 |
| H1 | 2018-07-01 | **2021-07-01** | 2026-11-13 | 32.718 | 101 | 480 | **36** |
| M1 | 2026-01-01 | 2026-01-01 | 2026-11-06 | 301.877 | 11 | 29.049 | 1 |

> **Mengapa ada `usable_start_date`.** File `h1_*.parquet` dari 2018-07 s/d
> 2021-06 berisi 25–28 bar per bulan, bukan bar jam-jaman: itu **lilin harian yang
> tersimpan dengan nama H1**. H1 yang benar-benar per jam baru ada sejak
> **2021-07-01** (471 bar bulan itu). Mengiklankan "H1 sejak 2018" berarti
> menjual 27 lilin harian sebagai replay per jam, jadi bulan seperti itu
> diklasifikasikan `sparse_months` dan tidak pernah dipakai sebagai pilihan
> default.
>
> **`start_date` = awal bulan file pertama, bukan bar pertama.** Katalog memakai
> ISO awal bulan (`2025-06-01`) karena satu file = satu bulan; bar M5 paling awal
> yang benar-benar ada adalah **2025-06-18** (lihat tabel audit
> `scripts/verify_parquet_cache.py`). `meta.start_date` pada payload selalu tanggal
> bar sungguhan, jadi UI harus memakai nilai dari payload, bukan dari katalog.
>
> Aturan sparse: satu bulan dianggap sparse bila jumlah bar-nya $< 25\%$ dari
> median bulan pada timeframe tersebut (`_DENSITY_RATIO = 0.25`). Ini menandai 36
> bulan H1 (2018-07→2021-06) dan satu bulan berjalan pada setiap timeframe lain
> (2026-11, ingest belum selesai). Bulan sparse **tidak diblokir** — user tetap
> boleh memilihnya — tetapi payload menyertakan peringatan (§5.2).
>
> **Dibuktikan ke broker, bukan diasumsikan (2026-11-16).**
> `scripts/probe_h1_history.py` meminta H1 dan D1 langsung ke terminal MT5 untuk
> sepuluh bulan sampel pada simbol `XAUUSDm`. Hasilnya: 2018-07 s/d 2021-06
> mengembalikan jumlah bar H1 **persis sama** dengan D1 (28/28, 26/26, 26/26,
> 26/26, 27/27 — rasio 1,0), sedangkan 2021-07 dan sesudahnya memberi rasio
> 17,4–18,9 (471–530 bar H1 vs 27–28 D1). Artinya server broker memang hanya
> menyimpan **lilin harian** sebelum 2021-07 dan mengirimkannya untuk permintaan
> H1; cache sudah merupakan maksimum yang jujur. Tidak ada yang bisa diunduh
> ulang, dan peringatan sparse adalah jawaban yang benar. Probe yang sama
> menunjukkan M15 intraday baru mulai sekitar **2022-08**.
>
> Angka lama — H1/M15 mulai 2017-01-01 dengan 62.400 / 249.600 bar, M5 mulai
> 2019-01-01 dengan 748.800 bar — adalah karangan dan sudah dicabut.


### 5.2. Endpoint: `GET /api/replay/data`
Mengambil kumpulan lilin murni untuk periode dan timeframe yang dipilih.

**Dispatch dua bentuk payload (penting).** Endpoint ini melayani dua konsumen
selama transisi Epic 3 → Epic 4:

| Kondisi | Bentuk respons | Pemakai |
| :--- | :--- | :--- |
| `period_mode` **dikirim** (bahkan kosong-string tidak; harus nilai valid) | `{"meta", "candles"}` murni | Workstation price action baru |
| `period_mode` **tidak dikirim** | payload legacy penuh (`trades`, `zones`, `equity_curve`) | Picker paritas benchmark, sampai Epic 4 menggantinya |

Payload legacy tidak pernah diam-diam berubah bentuk: tanpa `period_mode`,
parameter `session_id` / `strategy` / `rr_ratio` tetap berlaku seperti sebelumnya.

**Query Parameters (mode murni):**
* `timeframe`: `M5` \| `M15` \| `H1` \| `M1` (default: `M5`)
* `period_mode`: `month` \| `year` \| `multi_month` \| `custom` \| `all`
* `year`: `2018` s/d `2026` (wajib untuk `month` dan `year`)
* `month`: `1` s/d `12` (wajib untuk `month`)
* `start_date`: `YYYY-MM-DD` (wajib untuk `multi_month` dan `custom`)
* `end_date`: `YYYY-MM-DD` (wajib untuk `multi_month` dan `custom`)

**Aturan resolusi periode:**
- `month` → satu file bulan; `year` → seluruh bulan pada tahun itu; `all` → semua
  bulan yang ada untuk timeframe tersebut.
- `custom` / `multi_month` → bulan dianggap ikut bila rentang kalendernya
  **beririsan** dengan `[start_date, end_date]`, lalu bar dipangkas per hari
  (`00:00 UTC` awal s/d `24:00 UTC` akhir). `tz="UTC"` wajib: `date` polos adalah
  tengah malam *naive*, dan `.timestamp()` akan membacanya sebagai zona waktu
  mesin sehingga jendela bergeser.
- Rentang tanpa data → **HTTP 404** dengan kalimat yang menyebut cakupan nyata,
  mis. `Tidak ada data M5 pada Januari 2019. Data M5 tersedia 2025-06-01 s/d
  2026-11-06 (98.670 bar dalam 18 bulan).`
- `timeframe` / `period_mode` tak dikenal → 404 dengan daftar pilihan yang sah;
  tanggal salah format → 400.

**Response Payload Schema (Pure Price Action):**
```json
{
  "meta": {
    "symbol": "XAUUSD",
    "timeframe": "M5",
    "period_mode": "month",
    "period_label": "Oktober 2026",
    "start_date": "2026-10-01",
    "end_date": "2026-10-30",
    "total_bars": 6048,
    "first_bar_time": 1790812800,
    "last_bar_time": 1793393700,
    "months_loaded": 1,
    "warnings": []
  },
  "candles": [
    {
      "time": 1790812800,
      "open": 4156.244,
      "high": 4156.244,
      "low": 4150.854,
      "close": 4151.117,
      "volume": 785.0
    }
  ]
}
```

**`meta.warnings`** — daftar kalimat (boleh kosong) untuk kualitas data. Muncul
saat periode yang diminta memuat bulan sparse, mis.:

```
"Januari 2019 hanya berisi 27 bar H1 (bulan normal ~480 bar).
 Data H1 yang rapat baru tersedia sejak 2021-07-01."
```

Peringatan ini **tidak** menggagalkan request dan tidak mengubah `candles`; UI
wajib menampilkannya sebagai banner agar user tidak mengira 27 lilin itu satu
bulan penuh.

*(Contoh di atas adalah bar pertama `m5_2026_10.parquet` yang sebenarnya — perhatikan
3 desimal dan `volume` dari `tick_volume`. Spesifikasi lama menampilkan harga 2
desimal dan `volume: 2223` yang tidak berasal dari data mana pun. Jalur murni
**tidak** membulatkan harga ke 2 desimal; `load_candles()` mempertahankan presisi
sumber, sedangkan pembulatan hanya tersisa di jalur legacy `_candle_rows()`.)*
*(Catatan: Array `trades` dan `zones` bot dihilangkan total dari payload. Klaim lama
"memangkas ukuran transfer hingga 40%" **salah** dan sudah dicabut: pada M5 Oktober
2026 payload legacy 613.281 byte dan payload murni 637.949 byte, karena lilin
mendominasi dan presisi 3 desimal menambah ~4 byte per bar. Yang benar-benar
memangkas transfer adalah `GZipMiddleware`: 637.949 → 132.169 byte (−79%), dan
itulah angka yang boleh disebut.)*

**Cache.** LRU in-process 6 entri, kunci `(timeframe, period_mode, year, month,
start_date, end_date, bulan-bulan terpilih)`. Panggilan kedua dengan parameter
identik mengembalikan objek yang sama (tanpa rebuild, tanpa re-read parquet);
`clear_pure_cache()` dipakai test untuk mengosongkan.

---

## 6. Spesifikasi Interaksi Frontend (UI/UX Engine)

### 6.1. Panel Toolbar & Kontrol Periode
Toolbar diatur menjadi 4 kelompok kontrol ergonomis:

1. **Kelompok 1: Selector Periode & Timeframe:**
   - **Mode Dropdown / Radio:**
     - `Per Bulan`: Pilih Tahun (2018–2026) $\rightarrow$ Pilih Bulan (Jan–Des).
     - `Rentang Bulan`: Pilih Dari (Bulan/Tahun) $\rightarrow$ Ke (Bulan/Tahun).
     - `Tahunan`: Tombol cepat (2018, 2019, ..., 2026, atau `Semua Data`).
     - `Custom Date`: Input kalender `start_date` dan `end_date`.
     - `Semua Data`: memuat seluruh bulan yang tersedia untuk TF terpilih. **Batas aman 120.000 bar**: TF yang melebihi batas (M1 = 301.877 bar) dinonaktifkan dengan tooltip penjelas dan diarahkan ke Per Bulan/Rentang Bulan, karena memuat ~30 MB JSON akan membekukan tab.
   - **Pill Timeframe:** Digenerate dari `timeframe_coverage` (bukan hardcode) sehingga `M5`, `M15`, `H1`, dan `M1` muncul sesuai data yang benar-benar ada. Tombol otomatis disabled bila timeframe itu tidak punya bulan pada periode terpilih — dicek lewat `available_months` (mode bulan), `years` (mode tahun), atau irisan `start_date`/`end_date` (rentang/custom). Contoh: M5 sebelum 2025-06, M15 sebelum 2022-11.
   - **Tombol Muat:** Tombol `Muat Replay` dengan indikator loading halus (disabled + label berubah). Saat halaman dibuka, `default_selection` dari `/coverage` langsung dimuat otomatis agar chart tidak kosong.
   - **Banner Peringatan:** `meta.warnings` dari payload ditampilkan sebagai banner non-blocking di atas chart (mis. H1 Januari 2019 hanya 27 bar), dan hilang sendiri saat periode berganti ke data rapat. Pesan 404/400 dari `detail` ditampilkan apa adanya.

2. **Kelompok 2: Kontrol Pemutaran (Transport Controls):**
   - **Mundur 1 Bar (`⏮`):** Shortcut keyboard `ArrowLeft` ($\leftarrow$).
   - **Play / Pause (`▶ / ⏸`):** Shortcut keyboard `Spacebar`.
   - **Maju 1 Bar (`⏭`):** Shortcut keyboard `ArrowRight` ($\rightarrow$).
   - **Badge Status:** `STOPPED`, `PLAYING`, `PAUSED`, `COMPLETED`.
   - **Indikator Bar:** `Index / Total Bars` (misal: `1.240 / 6.048`).

3. **Kelompok 3: Pengali Kecepatan (Speed Pills):**
   - Pilihan: `0.5x`, `1x`, `2x`, `5x`, `10x`, `25x`, `50x`, `Max`.
   - Pada kecepatan `Max`, engine menyapu dataset secara proporsional (~4 detik per sesi) tanpa menjatuhkan frame rate.

4. **Kelompok 4: Utilitas & Fullscreen:**
   - **Tombol Fullscreen (`⛶ Fullscreen`):** Shortcut keyboard `F`.
   - **Scrubber Bar (Timeline Slider):** Menampilkan posisi persentase replay dengan tooltip tanggal & jam.

### 6.2. Logika Interaksi Chart (Smart Auto-Follow & Free Pan/Zoom)

| Status Replay | Perilaku Zoom (Roda Mouse / Pinch) | Perilaku Pan (Drag Kiri / Kanan) | Perilaku Viewport |
| :--- | :--- | :--- | :--- |
| **`PLAYING`** | **Aktif Bebas:** Mengubah `barSpacing` tanpa memutus auto-follow | Jika user menggeser chart ke masa lalu, auto-follow berhenti sejenak dan muncul tombol `⬇ Ikuti Lilin` | Ujung kanan chart selalu menempel mengikuti lilin baru yang terbentuk |

> **Aturan tepi (edge catch-up), ditambahkan setelah bug "lilin kepotong" (2026-11-16).**
> Auto-follow tidak boleh mati permanen hanya karena satu drag. Saat `PLAYING` dan
> auto-follow sedang lepas, setiap kali lilin aktif maju, chart mengecek apakah lilin
> **sebelumnya** masih berada di dalam jendela yang terlihat (`from ≤ watermark ≤ to`).
> Bila ya, dan lilin baru sudah menyentuh tepi kanan (`target ≥ to − 0,5`), auto-follow
> menyala kembali dan viewport ikut bergeser — lilin yang sedang ditonton tidak pernah
> jalan keluar layar. Bila user sengaja memarkir jendela ke masa lalu sehingga lilin
> aktif sudah di luar jendela, follow **tetap** lepas dan viewport tidak digeser paksa;
> tombol `⬇ Ikuti Lilin` yang mengembalikannya. Drag kecil 1–4 bar juga tidak langsung
> di-snap balik — follow baru menyala saat lilin benar-benar menyentuh tepi.
| **`PAUSED`** | **Aktif Bebas:** Memperbesar / memperkecil struktur teknikal | **Bebas 100%:** User dapat menggeser sejauh apa pun ke riwayat masa lalu layaknya TradingView | Tidak ada pergerakan paksa dari sistem |
| **`TEKAN PLAY`** | Tetap mempertahankan skala zoom terakhir | Mengembalikan fokus ke lilin aktif | Viewport secara mulus mengunci (*snap*) kembali ke ujung kanan lilin aktif |

> **Aturan sumbu dominan, ditambahkan setelah bug "drag sumbu harga memutus follow" (2026-11-16).**
> Zoom tidak lagi ditebak dari selisih jumlah bar (ambang kasar 0,8 bar membuat zoom roda
> mouse yang datang bertahap terbaca sebagai pan). Klasifikasi sekarang: **`barSpacing`
> berubah → zoom** (toleransi relatif 1e-6), dan saat follow aktif tepi kanan langsung
> di-re-pin ke `watermark + 6` supaya lilin tidak tergelincir selama zoom.
>
> Untuk drag, arah gesture ditentukan dari **sumbu dominan pointer**, bukan dari besar
> pergeseran waktu: `pointerdown` mencatat titik awal dan apakah tekanannya jatuh di strip
> sumbu harga; `pointermove` mengunci sumbu setelah gerak > 4 px (`|dx| ≥ |dy|` →
> horizontal). Cabang pan hanya dievaluasi untuk gesture horizontal — drag vertikal
> (meregangkan harga) dan drag di strip sumbu harga **tidak pernah** mengubah status
> follow, dan tepi kanan di-re-pin selama drag berlangsung. Bukti: drag vertikal dengan
> drift horizontal 25 px (≈3,6 bar) dulu mematikan follow (`to` 7,71 → 5,84), sekarang
> tetap `following=true` dengan `to` menempel di `watermark + 6`. Pan horizontal asli
> tetap memutus follow dan memunculkan tombol `⬇ Ikuti Lilin`.

### 6.3. Mode Layar Penuh (Native Fullscreen)
* Dijalankan pada kontainer utama chart replay via `element.requestFullscreen()`. Bila browser menolak (tanpa user activation), jatuh ke fallback class `.is-fullscreen` sehingga layout tetap penuh.
* **Heads-Up Display (HUD):**
  - Melayang semi-transparan di sudut kanan atas **secara permanen** (tidak hanya di fullscreen; di fullscreen ia menjadi satu-satunya chrome karena toolbar ikut tersembunyi bersama kontainer).
  - Menampilkan:
    * Tanggal & Jam Bar aktif (format: `YYYY-MM-DD HH:MM UTC` dan waktu lokal).
    * Pembacaan OHLC bar aktif (`O`, `H`, `L`, `C`, `Range $`).
    * Progres Replay (`0.0%` s/d `100.0%`).
* **Exit Fullscreen:**
  - Menekan tombol `Esc` atau tombol `⛶` akan mengembalikan layout dashboard standar.
  - Listener `fullscreenchange` otomatis memicu `chart.resize()` sehingga candlestick tidak terdistorsi.

---

## 7. Rencana Verifikasi Kualitas & Non-Fungsional

1. **Performa Rendering 60 FPS:**
   Rendering lilin per frame saat replay berjalan tetap mempertahankan batas visual `220 bars window` atau menggunakan `series.update()` satu per satu pada kecepatan standar, menjaga GPU dan memori browser tetap dingin.
2. **Kemandirian Jaringan (Zero-Lag Replay):**
   Setelah payload sesi di-load sekali di memori browser, seluruh operasi pemutaran, pausing, stepping, dan scrubbing berjalan 100% di browser tanpa request jaringan tambahan.
3. **Kesiapan Zero-CLI:**
   User cukup meluncurkan `Start_Assistant.bat` atau `Start_Assistant.vbs`, browser otomatis terbuka di `http://localhost:8000`, dan langsung siap untuk latihan price action.
4. **Suite Verifikasi Otomatis (dijalankan 2026-11-16, semua hijau):**
   | Perintah | Cakupan | Hasil |
   | :--- | :--- | :--- |
   | `.venv\Scripts\python.exe -m pytest -q` | backend + katalog + paritas benchmark | **119 passed** |
   | `node --test tests/js/replay_engine.test.js` | controller replay (clock, step, seek, cache) | **34 pass** |
   | `.venv\Scripts\python.exe scripts\verify_pure_replay.py` | E2E browser (API, selector, transport, follow/zoom/pan, fullscreen) | **73 checks, exit 0** |
   | `.venv\Scripts\python.exe scripts\verify_parquet_cache.py` | integritas 179 file parquet | **528.207 bar, 100% valid** |
   | `.venv\Scripts\python.exe scripts\repair_bar_cache_schema.py --check` | drift skema 9 kolom | **0 drift** |
   > `scripts/verify_replay_ui.py` (56 cek) sudah **dihapus** karena menguji picker benchmark, R:R preset, trade drawer, dan equity HUD yang dihilangkan di Epic 4. Salinannya diarsipkan di `_legacy_epic4/scripts/`. Gerbang UI yang berlaku sekarang hanya `verify_pure_replay.py`.
