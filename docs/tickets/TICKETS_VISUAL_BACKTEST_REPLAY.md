# TIKET KERJA REKAYASA TEKNIS
## Interactive Visual Backtest Replay Engine (XAUUSD M5/M15 Scalper)

**Dokumen Tiket:** `TICKET-REPLAY-01`  
**Spesifikasi Acuan:** [`SPECIFICATION_VISUAL_BACKTEST_REPLAY.md`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/docs/spec/SPECIFICATION_VISUAL_BACKTEST_REPLAY.md)  
**Doktrin Tertinggi:** [`AGENTS.md`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/AGENTS.md)

---

## Daftar Epic & Tiket Pengerjaan

### Epic 1: Replay Data Pipeline & Backend API
* **`T-REP-01: Replay Data Aggregator & Serializer Engine`**
  * *Tujuan:* Membuat modul backend di `src/assistant/replay_engine.py` yang membaca bar historis M5/M15 dari cache parquet (`data/cache_bars/`), menjalankan strategi `DualRetestScalperStrategy` (Mode A Murni / Dual), dan mengemas seluruh urutan lilin, event entry/exit, SL/TP, PnL, serta zona retest ke dalam struktur data yang terindeks rapi.
  * *Deliverable:* Modul `src/assistant/replay_engine.py` dengan fungsi `generate_replay_session()`.

* **`T-REP-02: FastAPI Replay Endpoints`**
  * *Tujuan:* Menyediakan endpoint REST API di `src/assistant/app.py`:
    - `GET /api/replay/sessions`: Daftar opsi rentang pengujian (misal: 2 Tahun, 4 Tahun, atau per bulan).
    - `GET /api/replay/data`: Mengirim payload terkompresi JSON berisi seluruh lilin dan daftar trade event ke browser.
  * *Deliverable:* Endpoint `/api/replay/*` terdaftar di FastAPI server.

---

### Epic 2: Frontend Replay State Machine & Incremental Renderer
* **`T-REP-03: Client-Side Replay Clock & State Machine`**
  * *Tujuan:* Membangun engine state machine di `src/assistant/static/js/replay_engine.js` yang mengelola status pemutaran (`STOPPED`, `PLAYING`, `PAUSED`, `SEEKING`, `COMPLETED`). Mengatur loop pewaktu (*timer/requestAnimationFrame*) yang terkalibrasi dengan pengali kecepatan (*speed multiplier*).
  * *Deliverable:* Class `ReplayController` di JavaScript.

* **`T-REP-04: Incremental Bar Appender with Lightweight Charts`**
  * *Tujuan:* Mengintegrasikan TradingView Lightweight Charts agar mampu menambahkan lilin satu per satu (*incremental tick-by-tick / bar-by-bar update*) menggunakan `candlestickSeries.update(bar)` secara efisien tanpa lag dan tanpa merender ulang chart dari awal.
  * *Deliverable:* Fungsi `appendBar(index)` dan `seekTo(targetIndex)`.

---

### Epic 3: Visual Trade Markers & Active Level Lines
* **`T-REP-05: Dynamic Entry & Exit Marker Visualizer`**
  * *Tujuan:* Menampilkan penanda grafis pada lilin saat event trading terjadi:
    - **Entry Marker:** Panah hijau di bawah candle untuk `BUY`, atau panah merah di atas candle untuk `SELL`, lengkap dengan label harga dan lot.
    - **Exit Marker:** Ikon centang hijau bertuliskan `TP HIT (+PnL)` atau ikon silang merah bertuliskan `SL HIT (-PnL)` saat posisi ditutup.
  * *Deliverable:* Modul marker mapping di `src/assistant/static/js/replay_markers.js`.

* **`T-REP-06: Active Trade Price Lines & Zone Shading`**
  * *Tujuan:* Selama ada posisi aktif yang berjalan:
    - Membuat garis horizontal dinamis pada chart: Garis Entry (biru), Garis TP (hijau putus-putus), Garis SL (merah putus-putus).
    - Otomatis menghapus garis-garis tersebut begitu posisi mencapai TP atau SL.
    - Menampilkan kotak zona retest (RBS / SBR) pada lilin M5.
  * *Deliverable:* Manajer garis harga aktif menggunakan `series.createPriceLine()`.

---

### Epic 4: Playback Controls, Speed Slider & Real-Time HUD
* **`T-REP-07: Interactive Playback Control Toolbar`**
  * *Tujuan:* Membuat komponen UI toolbar pemutar di atas chart:
    - Tombol `Play / Pause` (Shortcut: `Spacebar`).
    - Tombol `Step Forward (1 Bar)` (Shortcut: `Panah Kanan`).
    - Tombol `Step Back (1 Bar)` (Shortcut: `Panah Kiri`).
    - Tombol preset kecepatan: `0.5x`, `1x`, `2x`, `5x`, `10x`, `25x`, `50x`, `Max`.
    - Timeline scrubber bar untuk melompat bebas ke tanggal mana saja.
  * *Deliverable:* Komponen HTML/CSS/JS di `index.html` dan `replay.css`.

* **`T-REP-08: Real-Time HUD & Compounding Equity Tracker`**
  * *Tujuan:* Menampilkan panel melayang (*Heads-Up Display*) transparan di sudut kanan atas chart:
    - Saldo modal compounding berjalan ($10.000 $\rightarrow$ \$18.822).
    - Floating PnL posisi terbuka yang berfluktuasi sesuai harga *high/low/close* lilin aktif.
    - Win Rate berjalan dan jumlah trade yang sudah ditutup.
    - Jam & tanggal bar saat ini (UTC).
  * *Deliverable:* Komponen HUD real-time di UI.

---

### Epic 5: Tab Integration, Mini Equity Curve & Zero-CLI Verification
* **`T-REP-09: Synchronous Mini Equity Curve Sub-Chart`**
  * *Tujuan:* Menyematkan grafik garis kecil di bawah chart candlestick utama yang menampilkan kurva saldo ekuitas yang bergerak maju secara sinkron setiap kali sebuah trade selesai di-replay.
  * *Deliverable:* Sub-chart mini ekuitas terhubung ke controller replay.

* **`T-REP-10: Dashboard Tab Integration & Zero-CLI Verification`**
  * *Tujuan:* Mengintegrasikan tab **"Visual Replay"** ke dalam navbar utama dashboard (`src/assistant/templates/index.html`), memastikan dapat diluncurkan langsung dengan satu klik via `Start_Assistant.bat` tanpa menyentuh command prompt.
  * *Deliverable:* Tab Replay aktif dan teruji di browser `http://localhost:8000`.
