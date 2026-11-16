# TIKET KERJA REKAYASA TEKNIS
## Dedicated Pure Price Action Replay & Simulator Suite (XAUUSD M5, M15, H1)

**Dokumen Tiket:** `TICKET-PA-REPLAY-01`  
**Status Proyek:** IN PROGRESS (Epic 1 & 2 Selesai / Siap Menuju Epic 3)  
**Spesifikasi Acuan:** [`SPECIFICATION_PURE_PRICE_ACTION_REPLAY.md`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/docs/spec/SPECIFICATION_PURE_PRICE_ACTION_REPLAY.md)  
**Doktrin Tertinggi:** [`AGENTS.md`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/AGENTS.md)

---

## 1. Papan Status Pelaksanaan (Execution Status Board)

| ID Epic | Nama Epic & Deskripsi | Target Tiket | Status Pelaksanaan | Catatan Validasi |
| :---: | :--- | :---: | :---: | :--- |
| **EPIC 1** | **Data Pipeline Historis (M5, M15, H1, M1) & Ingestion** | `T-PAR-01`, `T-PAR-02` | **SELESAI (100%) + TER-AUDIT** | 179 file parquet, 528.207 bar; cakupan nyata H1 2018-07 / M15 2022-11 / M5 2025-06 / M1 2026-01. **Bukan 10 tahun penuh.** |
| **EPIC 2** | **Dead Code Elimination (Pembersihan Sinyal Live)** | `T-PAR-03`, `T-PAR-04`, `T-PAR-05` | **SELESAI (100%)** | 5 modul backend + 5 JS + 2 test dihapus; `app.py` 6 route; 100 pytest / 34 node / 56 UI check hijau saat itu |
| **EPIC 3** | **Backend Replay API & Katalog Dinamis** | `T-PAR-06`, `T-PAR-07` | **SELESAI (100%)** | Endpoint `/coverage` + dispatch `period_mode`; payload `{meta,candles}` tanpa pembulatan; 19 test baru. H1 rapat baru sejak **2021-07-01** (2018-07→2021-06 = 36 bulan sparse) |
| **EPIC 4** | **Frontend TradingView-Grade Interaction & Fullscreen** | `T-PAR-08`, `T-PAR-09`, `T-PAR-10` | **SELESAI (100%)** | 4 file frontend ditulis ulang; selector digenerate dari coverage, follow/zoom/pan & fullscreen terverifikasi browser. HUD + scrubber + 8 speed pill |
| **EPIC 5** | **Verifikasi E2E & Smoke Testing Otomatis** | `T-PAR-11` | **SELESAI (100%)** | `scripts/verify_pure_replay.py` → **67/67 check, exit 0** (API+gzip, selector, transport, follow, fullscreen, M5/M15/H1). Suite lama 56 cek sudah tidak valid |

---

## 2. Rincian Tiket & Rekam Jejak Eksekusi

### Epic 1: Data Pipeline Historis (M5, M15, H1, M1) & Ingestion Engine
*Status: SELESAI (COMPLETED 100%) — lihat "Audit Pasca-Eksekusi" di bawah*

* **`T-PAR-01: Historical Bar Downloader (scripts/download_history_10y.py)`**
  * **Status:** **`[SELESAI / DONE]`** (Dieksekusi: 2026-11-16 16:21 WIB)
  * **Tujuan:** Membuat skrip CLI mandiri yang menghubungkan ke terminal MT5, mendeteksi simbol aktif emas (`XAUUSDm`), dan mengunduh bar OHLCV per bulan untuk rentang yang diminta **1 Januari 2017 s/d 16 November 2026** pada timeframe **H1**, **M15**, **M5** (plus **M1**).
  * **Kriteria Penerimaan (Acceptance Criteria):**
    - [x] Mengambil data per batch bulanan dengan tanggal mulai 1 Januari 00:00:00 UTC di setiap tahun.
    - [x] Menyimpan file ke `data/cache_bars/{timeframe}_{year}_{month:02d}.parquet`.
    - [x] Skema konsisten: `time` (int64 epoch), OHLC (`Float64`, presisi sumber dipertahankan — lihat §3.3), `tick_volume` (uint64), `spread` (int32), `real_volume` (uint64), `timestamp` (datetime UTC naive).
    - [x] Menangani limitasi broker untuk M5 secara adaptif (*graceful fallback* tanpa crash).
    - [x] Menampilkan log ringkas progres dan jumlah bar yang tersimpan.
  * **Hasil Eksekusi:**
    - Deliverable: [`scripts/download_history_10y.py`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/scripts/download_history_10y.py)
    - Mengunduh dan menstandardisasi 179 file parquet: H1 (101 bulan, mulai Juli 2018), M15 (49 bulan, mulai Nov 2022), M5 (18 bulan, mulai Juni 2025), M1 (11 bulan, mulai Jan 2026).

* **`T-PAR-02: Parquet Cache Integrity & Metadata Verifier`**
  * **Status:** **`[SELESAI / DONE]`** (Dieksekusi: 2026-11-16 16:26 WIB)
  * **Tujuan:** Membuat skrip audit cepat untuk memverifikasi kelengkapan cache parquet: memeriksa urutan waktu monoton naik, tidak ada lonjakan nilai NaN/korup, kesesuaian skema kontrak §3.3, dan menghitung total bar yang berhasil terkumpul.
  * **Kriteria Penerimaan:**
    - [x] Memverifikasi integritas seluruh file parquet di `data/cache_bars/`.
    - [x] Memvalidasi aturan konsistensi OHLC ($Low \le Open \le High$, $Low \le Close \le High$).
    - [x] Memvalidasi monotonitas waktu (timestamp strictly ascending).
    - [x] Memvalidasi kelengkapan kolom kontrak §3.3 (bukan sekadar `time`/OHLC).
    - [x] Menghasilkan ringkasan ketersediaan data per tahun dan per timeframe.
  * **Hasil Eksekusi:**
    - Deliverable: [`scripts/verify_parquet_cache.py`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/scripts/verify_parquet_cache.py)
    - Hasil audit 2026-11-16: 179 file lolos uji integritas 100% (Total: 528.207 bar, **16,76 MB**, 0,61 detik).
    - Regresi benchmark aman: **125/125 pytest** lulus, **48/48** node js test lulus.

#### Audit Pasca-Eksekusi (2026-11-16) — Temuan & Perbaikan

Papan status Epic 1 di atas **benar** (skrip ada, jalan, dan datanya nyata), tetapi
audit menemukan tiga cacat yang tidak tertangkap oleh checklist lama:

1. **Volume palsu di seluruh data 2026.** 33 file (`m5_2026_*`, `m15_2026_*`,
   `m1_2026_*`) dibuat oleh `scripts/prepare_months_01_02_03.py` dari tick parquet,
   bukan `copy_rates_range()`. File itu tidak punya `tick_volume` / `spread` /
   `real_volume` dan menyisakan kolom `__index_level_0__`. Akibatnya
   `replay_engine._candle_rows` diam-diam mengisi `"volume": 0.0` untuk **setiap
   bar 2026** — pane volume di chart datar dan tidak ada test yang menangkapnya.
2. **Skip-logic downloader buta skema.** Cek "sudah ada?" hanya melihat kolom
   `time`, sehingga file menyimpang dianggap sehat dan tidak akan pernah diperbaiki.
3. **`verify_parquet_cache.py` tidak memeriksa kontrak.** Skrip lolos 100% walau
   tiga kolom wajib hilang.

Perbaikan yang sudah dilakukan dan diverifikasi:

* `scripts/repair_bar_cache_schema.py` (baru) — merekonstruksi `tick_volume` /
  `spread` / `real_volume` dari tick parquet sumber pada bulan yang sama,
  membuang kolom pandas, menormalkan `timestamp` ke naive UTC, dan **menolak
  menulis jika OHLC bergeser satu nilai pun**. Re-audit: 0 file menyimpang.
* Bukti paritas: SHA-256 OHLC seluruh 179 file **identik** sebelum vs sesudah
  (`logs/_ohlc_baseline.json`). 0 bar tanpa volume. Angka benchmark Oktober 2026
  tetap `48 trade / +23,5% / WR 56,25%`.
* `download_history_10y.py` — skip-logic kini menolak file yang menyimpang
  (`stats["drifted"]`, exit code 1) dan **tidak** mengunduh ulang, karena
  re-download menggeser harga mid-price sebesar setengah spread (~+0,12) dan
  memutus paritas.
* `verify_parquet_cache.py` — kini memvalidasi kontrak 9 kolom §3.3.
* `pyproject.toml` — `testpaths = ["tests"]`; sebelumnya `pytest` polos menggantung
  >600 detik karena mengoleksi `scratch/` yang membaca ratusan MB parquet saat import.
* `tests/test_bar_cache_schema.py` (baru) — 5 test mengunci kontrak, paritas OHLC,
  idempotensi repair, dan konsistensi daftar kolom antar tiga skrip.

**Koreksi dokumentasi.** Klaim "10 Tahun Penuh" (2017→2026) tidak pernah benar:
H1 mulai **2018-07**, M15 **2022-11**, M5 **2025-06**, M1 **2026-01**. Angka
cakupan fiktif di Spec §5.1 (M5 "mulai 2019-01-01, 748.800 bar") sudah diganti
dengan cakupan nyata.


---

### Epic 2: Dead Code Elimination (Pembersihan Modul Sinyal)
*Status: SELESAI (COMPLETED 100%)*

> **Koreksi daftar file (2026-11-16).** Tiket lama menyebut `src/assistant/analyzer.py` dan
> `src/assistant/setups.py`, padahal kedua file itu **tidak pernah ada** di repo —
> fungsinya sudah lama digabung ke `smc_live.py` + `setup_state.py`. Daftar hapus yang
> benar (hasil pemetaan impor, bukan tebakan) adalah:

```text
src/assistant/streamer.py       ← satu-satunya pemakai smc_live + setup_state
src/assistant/smc_live.py       ← analyzer live (pengganti "analyzer.py")
src/assistant/setup_state.py    ← state machine setup (pengganti "setups.py")
src/assistant/reasoning.py      ← dipakai setup_state, ikut mati
src/assistant/journal.py        ← SQLite journal, dipakai streamer
tests/test_assistant_journal.py
tests/test_assistant_setup_state.py
static/js/stream.js, chart.js, overlay.js, setups.js, evaluation.js
```

* **`T-PAR-03: Backend Dead Code Elimination`**
  * **Status:** **`[SELESAI / DONE]`** (Dieksekusi: 2026-11-16)
  * **Tujuan:** Menghapus modul-modul backend yang tidak lagi digunakan untuk live signal bot agar sistem bersih, cepat, dan hemat sumber daya.
  * **Kriteria Penerimaan:**
    - [x] Server `app.py` berjalan bersih tanpa referensi ke modul sinyal lama.
    - [x] Test suite backend tidak mengalami error broken import.
  * **Hasil Eksekusi:**
    - 5 modul backend + 2 file test dihapus (25 test ikut hilang karena menguji kode mati).
    - `app.py` di-rewrite: `lifespan` tidak lagi menjalankan `BarStreamer`, tidak ada broadcaster/queue.
    - Route akhir (diverifikasi lewat `app.openapi()["paths"]`): `/api/health`, `/api/mt5/status`,
      `/api/mt5/connect`, `/api/mt5/disconnect`, `/api/replay/sessions`, `/api/replay/data`.
      Nol route `/ws/stream`, `/api/smc/*`, `/api/setups`, `/api/journal/*`.
    - `MT5Bridge` + `/api/mt5/*` dipertahankan sesuai tiket.
    - Regresi: **100/100 pytest lulus** (125 − 25 test kode mati), 0 broken import.
    - Backup 16 file asli di `_legacy_epic2/` (repo ini bukan git repo).

* **`T-PAR-04: Frontend Dead Code Elimination & App Consolidation`**
  * **Status:** **`[SELESAI / DONE]`** (Dieksekusi: 2026-11-16)
  * **Tujuan:** Menghapus file skrip JavaScript dan gaya CSS lama yang berhubungan dengan kartu setup sinyal, evaluasi live, overlay grafis sinyal, dan live chart.
  * **Kriteria Penerimaan:**
    - [x] Tidak ada error 404 pada network tab browser saat dashboard dimuat.
    - [x] Tidak ada variabel global sisa (`SmcStream`, `SmcSetups`, `SmcEvaluation`) di runtime window.
  * **Hasil Eksekusi:**
    - Dihapus: `stream.js`, `chart.js`, `overlay.js`, `setups.js`, `evaluation.js` (5 file).
    - `dashboard.css` 16.982 → 6.735 byte; aturan `.tabs`, `.tab-*`, `.live-grid`, `.chart-panel`,
      `.chart-container`, `.chart-readout`, `.overlay-legend`, `.setup-*`, `.eval-*`, `.tf-switch`,
      `.tf-btn`, `.panel-placeholder` dibuang. Shell header/status/badge/tombol MT5 dipertahankan.
    - `app.js` 9.765 → 6.931 byte; kini hanya polling `/api/mt5/status`, connect/disconnect, dan
      badge/meta/toast. Nol `SmcStream`/`SmcSetups`/`SmcEvaluation`/`WebSocket` (diverifikasi grep).
    - Bukti 404: seluruh `src=`/`href=` di `index.html` di-fetch → 200 OK.

* **`T-PAR-05: Redesain Layout Penuh di index.html`**
  * **Status:** **`[SELESAI / DONE]`** (Dieksekusi: 2026-11-16)
  * **Tujuan:** Menghapus navigasi tab lama (*Live*, *Evaluasi*, *Replay*) di `src/assistant/templates/index.html`. Mengubah area utama menjadi **Dedicated Replay Workstation** satu layar penuh.
  * **Kriteria Penerimaan:**
    - [x] Header memuat logo XAUUSD Replay Terminal dan cluster status MT5.
    - [x] Area utama 100% ditempati oleh Replay Workspace (Toolbar, Timeline Scrubber, Canvas Chart, Floating HUD).
  * **Hasil Eksekusi:**
    - `index.html` 17.193 → 13.576 byte. `.tabs`, `#pane-live`, `#pane-eval` dihapus; `#pane-replay`
      naik jadi viewport utama tanpa kelas `hidden`. `body { overflow: hidden }`, chart `minmax(0,1fr)`.
    - 70/70 ID kontrak replay + status MT5 utuh (nol ID replay hilang).
    - **`scripts/verify_replay_ui.py` ikut disesuaikan** (bukan diakali): 4 assertion lama yang
      menguji keberadaan tab diganti menjadi "legacy tab navigation removed", "replay workstation
      visible without a tab click", "workstation fits the viewport", dan "body pinned to the viewport".
      Jumlah cek tetap 56.
    - Bukti: `python scripts/verify_replay_ui.py --url http://127.0.0.1:8000` →
      **"All 56 UI checks passed."** (termasuk 48 trade drawer, paritas equity 12349.84, shortcut
      keyboard, dan viewport pendek 650px).


---

### Epic 3: Backend Replay API & Dynamic Period/Timeframe Catalog
*Status: SELESAI (COMPLETED 100%) — dieksekusi 2026-11-16*

* **`T-PAR-06: Dynamic Period & Timeframe Discovery Engine (replay_engine.py)`**
  * **Status:** **`[SELESAI / DONE]`** (Dieksekusi: 2026-11-16)
  * **Tujuan:** Memperbarui modul `src/assistant/replay_engine.py` agar memindai ketersediaan seluruh file parquet historis secara instan melalui metadata footer parquet.
  * **Kriteria Penerimaan:**
    - [x] Mengembalikan pemetaan ketersediaan data per tahun (2018–2026) dan per timeframe (M5, M15, H1, M1).
    - [x] Mendukung filter:
      1. Single Month (`year`, `month`)
      2. Multi-Month (`start_date`, `end_date`)
      3. Full Year (`year`)
      4. Custom Range (`start_date`, `end_date`)
      5. All (`all`)
    - [x] Menolak request rentang yang tidak memiliki data dengan pesan HTTP 404 yang ramah (menyebut cakupan nyata).
  * **Bukti eksekusi:**
    - API baru di `replay_engine.py`: `MonthFile`, `scan_timeframe_files()` (footer-only, cache terhadap mtime direktori), `timeframe_coverage()`, `sparse_months()`, `resolve_period()`, `period_label()`, `load_candles()`, `generate_pure_payload()`, `clear_pure_cache()`.
    - Endpoint baru `GET /api/replay/coverage`; `/api/replay/sessions` tetap ada dan sekarang menambahkan `available_years`, `timeframe_coverage`, `timeframes`, `period_modes`, `default_selection` **tanpa menghapus** kunci legacy (paritas benchmark tetap jalan sampai Epic 4).
    - Live: `GET /api/replay/coverage` → `M5 2025-06-01→2026-11-06 (98.670)`, `M15 2022-11-01→2026-11-06 (94.942)`, `H1 2018-07-01→2026-11-13 (32.718, usable 2021-07-01)`, `M1 2026-01-01→2026-11-06 (301.877)`; `default_selection` = M5 Oktober 2026.
    - 404 terverifikasi: `M5 month 2019-01`, `M15 year 2019`, `M5 custom 2019-01-01..2019-01-31`, `M1 month 2018-07`.
  * **Temuan audit (penting, mengubah klaim spec):** file `h1_*.parquet` 2018-07 s/d 2021-06 berisi 25–28 bar per bulan — lilin **harian** yang tersimpan dengan nama H1. H1 per jam yang sebenarnya baru ada sejak **2021-07-01** (471 bar). Karena itu katalog menerbitkan `usable_start_date` terpisah dari `start_date`, dan 36 bulan tersebut masuk `sparse_months` (ambang 25% × median bulan). Lihat Spec §5.1.
  * **Dibuktikan ke broker (2026-11-16):** `scripts/probe_h1_history.py` (read-only, tidak menulis parquet) meminta H1 dan D1 ke terminal MT5 untuk 10 bulan sampel pada `XAUUSDm`. 2018-07…2021-06 → H1 = D1 persis (rasio 1,0: 28/28, 26/26, 26/26, 26/26, 27/27); 2021-07…2026-10 → rasio 17,4–18,9 (471–530 bar H1). Kesimpulan: **server broker hanya punya lilin harian sebelum 2021-07** dan mengirimkannya saat diminta H1. Cache = maksimum jujur, tidak ada re-download, peringatan sparse benar. M15 intraday mulai ~2022-08.
  * **Verifikasi:** `tests/test_replay_catalog.py` — 19 test lulus (discovery, sparse, kelima period mode, penolakan argumen, pesan 404, cache identity, trim custom).

* **`T-PAR-07: Pure Price Action Payload Serializer (replay_api.py)`**
  * **Status:** **`[SELESAI / DONE]`** (Dieksekusi: 2026-11-16)
  * **Tujuan:** Menyederhanakan payload `/api/replay/data` agar murni berisi array lilin candlestick (`candles`) dan metadata periode/timeframe, tanpa membawa payload objek simulasi bot (`trades`, `zones`, `equity_curve`).
  * **Kriteria Penerimaan:**
    - [x] Response JSON memuat `meta` dan `candles` murni.
    - [~] Klaim "mengurangi ukuran payload hingga ~40%" **DICABUT — tidak benar**. Pengukuran nyata (M5 Oktober 2026, 6.048 bar): legacy 613.281 byte vs murni 637.949 byte, jadi murni **4% lebih besar**. Lilin mendominasi payload; `trades`/`zones`/`equity_curve` hanya ~4 KB, sementara 3 desimal menambah ~4 byte per bar. Pengurangan transfer yang nyata datang dari kompresi: `GZipMiddleware` menurunkan 637.949 → **132.169 byte (−79%)**.
    - [x] Cache in-memory LRU tetap bekerja efisien per (periode, timeframe).
  * **Bukti eksekusi:**
    - `GET /api/replay/data?period_mode=...` mengembalikan tepat `{meta, candles}`. Live: M5 Oktober 2026 → 6.048 bar, kunci payload persis `['candles','meta']`, lilin pertama `open 4156.244` (3 desimal dipertahankan, tidak dibulatkan).
    - Tanpa `period_mode`, respons tetap payload legacy penuh — dipagari oleh `test_data_endpoint_legacy_shape_is_untouched`.
    - `meta` kini memuat `period_mode`, `months_loaded`, dan `warnings`; `candles` bebas `trades`/`zones`/`equity_curve`.
    - Cache: LRU 6 entri dengan kunci menyertakan daftar bulan terpilih; panggilan kedua mengembalikan objek identik (`is` True, terverifikasi).
    - Trim custom diuji: M5 `2026-10-05..2026-10-07` → 828 bar (3 hari bursa, bukan 864 kalender); H1 `2026-10-01..2026-10-01` → tepat 24 bar.
  * **Catatan presisi:** `load_candles()` **tidak** membulatkan harga. Pembulatan 2 desimal hanya tersisa di `_candle_rows()` milik jalur legacy. Jalur murni mempertahankan presisi sumber (3 desimal untuk data turunan tick).

---

### Epic 4: Frontend TradingView-Grade Interaction, Dynamic Selectors & Fullscreen
*Status: SELESAI (COMPLETED 100%) — dieksekusi 2026-11-16*

* **`T-PAR-08: Period & Timeframe Selector Toolbar Component (replay.js & index.html)`**
  * **Status:** **`[SELESAI / DONE]`** (Dieksekusi: 2026-11-16)
  * **Tujuan:** Membangun antarmuka selector periode 2 tahap pada toolbar replay:
    - **Tahap 1 (Periode):** Toggle mode (*Per Bulan*, *Rentang Bulan*, *Tahunan*, *Custom Date*).
    - **Tahap 2 (Timeframe):** Tombol pill pilihan `M5`, `M15`, `H1`. Tombol otomatis dinonaktifkan jika data tidak tersedia untuk periode yang dipilih.
    - Tombol aksi `Muat Replay`.
  * **Kriteria Penerimaan:**
    - [x] Pengguna dapat memilih bulan atau tahun apa saja dalam rentang data yang tersedia dan langsung memuat lilinnya ke chart.
  * **Bukti eksekusi:**
    - 5 mode (`month`, `multi_month`, `year`, `custom`, `all`) dengan input adaptif; pill TF **digenerate dari `timeframe_coverage`** sehingga M5/M15/H1/M1 muncul sesuai data, dan dinonaktifkan presisi memakai `available_months`/`years`/rentang.
    - Terverifikasi browser: 2019-01 → M5 dan M15 disabled, H1 tetap aktif (sparse tapi ada); H1 2019-01 termuat 27 lilin + banner peringatan.
    - Buka halaman → `default_selection` (M5 Oktober 2026) langsung termuat otomatis, posisi `1 / 6.048`.
    - Pesan 404 backend (`end_date harus >= start_date`) tampil apa adanya di banner error.
  * **Catatan batas aman:** mode `Semua Data` menolak TF dengan total bar > 120.000 (M1 = 301.877) dan mengarahkan user ke Per Bulan/Rentang Bulan. Tanpa batas ini tab akan membeku memuat ~30 MB JSON.

* **`T-PAR-09: Smart Auto-Follow & Free Pan/Zoom Engine (replay_chart.js)`**
  * **Status:** **`[SELESAI / DONE]`** (Dieksekusi: 2026-11-16)
  * **Tujuan:** Mengimplementasikan kontrol pergerakan chart layaknya TradingView:
    - **Saat Play:** Ujung kanan chart otomatis maju mengikuti lilin baru (*auto-follow*), namun user tetap bebas mengubah level zoom (*barSpacing*) kapan saja tanpa memutus scrolling.
    - **Deteksi Manual Scroll:** Jika user men-drag chart ke masa lalu saat play, auto-follow berhenti dan muncul tombol mengambang `⬇ Ikuti Lilin Terbaru`.
    - **Saat Pause:** Auto-follow mati total. User bebas menggeser chart ke masa lalu sejauh apa pun untuk menganalisis struktur harga.
    - **Saat Play Kembali:** Viewport melakukan *smooth snap* kembali ke ujung kanan lilin aktif.
  * **Kriteria Penerimaan:**
    - [x] Chart tidak lagi "melawan" tangan user saat mencoba zoom atau pan.
    - [x] Stepping satu bar (maju/mundur) menggeser viewport secara presisi.
  * **Bukti eksekusi:**
    - `replay_chart.js` ditulis ulang (13,6 KB → 8,4 KB): candlestick saja, equity chart + zone primitive + marker dibuang.
    - State machine follow: `subscribeVisibleLogicalRangeChange` membedakan zoom (span berubah) dari pan (span konstan + `to` mundur > 2,5 bar), dengan guard `isProgrammaticScroll` agar gerakan sendiri tidak dianggap pan.
    - Terverifikasi: zoom saat PLAYING tetap `following=true` dan tepi kanan tetap menempel; drag ke masa lalu saat PLAYING → `following=false` + tombol ikuti muncul; klik tombol → follow pulih.
    - Saat PAUSED, viewport yang digeser 600 bar **tidak bergerak sedikit pun** setelah 500 ms (drift < 1 bar).
    - Step `⏮`/`⏭` bergerak tepat satu bar (0→1→0), termasuk pada M15.

* **`T-PAR-10: Native Fullscreen Manager & Minimalist Floating HUD`**
  * **Status:** **`[SELESAI / DONE]`** (Dieksekusi: 2026-11-16)
  * **Tujuan:** Menambahkan fungsionalitas mode layar penuh dan merampingkan tampilan HUD:
    - Tombol `⛶ Fullscreen` pada toolbar dan shortcut keyboard **`F`**.
    - Kontainer chart mengembang ke `100vw, 100vh` dengan listener `fullscreenchange` yang memicu `chart.resize()`.
    - HUD melayang transparan di sudut kanan atas menampilkan: Waktu Bar (UTC & Lokal), Status Playback, Harga OHLC terkini, dan Progres Bar.
  * **Kriteria Penerimaan:**
    - [x] Menekan `F` atau tombol Fullscreen beralih ke layar penuh tanpa distorsi rasio lilin.
    - [x] Menekan `Esc` keluar dari layar penuh dengan chart yang otomatis menyesuaikan ukurannya kembali.
  * **Bukti eksekusi:**
    - `F` masuk native fullscreen (`document.fullscreenElement` terisi), chart 556 px → 600 px tanpa distorsi; tombol berubah `⛶ Normal`; keluar → tombol `⛶ Fullscreen`, chart kembali 556 px, `scrollHeight == innerHeight` (tidak ada page scroll).
    - HUD melayang permanen (bukan hanya fullscreen) berisi status, progres, waktu UTC + lokal (`2026-10-01 00:00 UTC` / `2026-10-01 07:00 WIB`), OHLC 3 desimal, dan range $.
    - Scrubber punya tooltip tanggal+jam; 8 preset kecepatan (0.5x–50x + Max) benar-benar tersambung (`speed === 'max'`, dan Max menyapu sesi sampai `COMPLETED`).

---

### Epic 5: Verifikasi E2E & Smoke Testing
*Status: SELESAI (COMPLETED 100%)*

* **`T-PAR-11: E2E Headless Chrome Verification Suite (scripts/verify_pure_replay.py)`**
  * **Status:** **`[SELESAI / DONE]`** (Dieksekusi: 2026-11-16)
  * **Tujuan:** Menulis skrip verifikasi otomatis berbasis Chrome DevTools Protocol (CDP) untuk menguji seluruh fitur baru:
    - Pemuatan selector periode dan timeframe.
    - Pemutaran lilin Play/Pause/Step pada timeframe M5, M15, dan H1.
    - Transisi Fullscreen mode dan pemulihan ukuran window.
    - Pengujian zoom dan pan saat status PAUSED dan PLAYING.
  * **Kriteria Penerimaan:**
    - [x] Skrip keluar dengan exit code 0 dan seluruh assertion passed.
  * **Bukti eksekusi:**
    - `scripts/verify_pure_replay.py` — **67 check, exit 0**, mencakup kontrak API (termasuk gzip >70%), DOM selector, transport, follow/zoom/pan, M5+M15+H1 playback, fullscreen in/out, dan nol error console.
    - Suite lama `scripts/verify_replay_ui.py` (56 cek) mengunci UI benchmark yang sudah dibuang, sehingga tidak lagi valid. File itu **sudah dihapus** (2026-11-16) setelah konfirmasi user; salinan identik (SHA-256 cocok) tersimpan di `_legacy_epic4/scripts/verify_replay_ui.py` bila kelak ingin dirujuk.
    - Bukti tambahan: `pytest` 119 lulus, `node --test tests/js/replay_engine.test.js` 34 lulus, audit parquet 100% valid.
  * **Pembersihan lanjutan:** `src/assistant/static/js/replay_markers.js` (5,8 KB) dan `tests/js/replay_markers.test.js` (14 test) **dihapus** setelah Epic 4 karena nol referensi — marker trade ikut hilang bersama trade drawer. Node test turun 48 → 34. Backup: `_legacy_epic4/js/` dan `_legacy_epic4/tests/js/`.
