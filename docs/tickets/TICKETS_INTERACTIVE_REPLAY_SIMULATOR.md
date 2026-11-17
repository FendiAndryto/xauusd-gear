# TIKET KERJA REKAYASA TEKNIS
## Interactive Strategy Simulator & Drawing Suite (XAUUSD Replay Terminal)

**Dokumen Tiket:** `TICKET-SIM-REPLAY-01`  
**Status Proyek:** READY FOR EXECUTION (Blocker B1-B3 & Referensi File Terverifikasi)  
**Spesifikasi Acuan:** [`SPECIFICATION_INTERACTIVE_REPLAY_SIMULATOR.md`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/docs/spec/SPECIFICATION_INTERACTIVE_REPLAY_SIMULATOR.md)  
**Doktrin Tertinggi:** [`AGENTS.md`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/AGENTS.md)

---

## 1. Papan Status Pelaksanaan & Gerbang Fase (Execution Board)

### 1.1. Gerbang Fase Eksekusi
Eksekusi dibagi menjadi 5 fase terisolasi. Setiap fase memiliki kriteria penerimaan yang harus diverifikasi sebelum melangkah ke fase berikutnya:

```
[FASE 1: T-SIM-01, T-SIM-02] ──► HUD Kiri Atas & Toggle Shortcut (H)
                                  (Verifikasi: CSS + DOM, Lilin Kanan Bebas, CDP Test)
                                          │
                                          ▼
[FASE 2: T-SIM-03, T-SIM-04] ──► Left Toolbar Dock & Canvas Overlay Sync
                                  (Verifikasi: Pointer-events auto/none, SubscribeClick, Chart Handle)
                                          │
                                          ▼
[FASE 3: T-SIM-05A, 05B, 05C]──► Core Drawing Tools (H-Line, Box, Trendline, Ruler, Selection)
                                  (Verifikasi: Alt+H handler, rubber-band preview, persistensi lintas TF)
                                          │
                                          ▼
[FASE 4: T-SIM-06, T-SIM-07] ──► Position Tools & Bar-by-Bar Simulator Engine
                                  (Verifikasi: B1 Lot formula, B2 Manual close, B3 Pessimistic tie-break via node --test)
                                          │
                                          ▼
[FASE 5: T-SIM-08]           ──► LocalStorage Persistensi & E2E Verification Suite
                                  (Verifikasi: Extend scripts/verify_pure_replay.py, Zero console errors)
```

| ID Tiket | Ringkasan Tugas | Target File | Status |
| :---: | :--- | :--- | :---: |
| **`T-SIM-01`** | Relokasi HUD ke Kiri Atas & Format Horizontal Kompak | `replay.css`, `index.html`, `replay.js` | **`[SELESAI / DONE 100%]`** |
| **`T-SIM-02`** | HUD Pointer-Events & Shortcut Toggle `H` | `replay.css`, `replay.js`, `index.html` | **`[SELESAI / DONE 100%]`** |
| **`T-SIM-03`** | Toolbar Vertikal Sisi Kiri (Width 48px) & Overflow-Safe Tooltips | `index.html`, `replay.css`, `replay.js` | **`[SELESAI / DONE 100%]`** |
| **`T-SIM-04`** | Layer Canvas Overlay, Pointer-Events State & Official Chart API | `replay_canvas.js`, `replay_chart.js` | **`[SELESAI / DONE 100%]`** |
| **`T-SIM-05A`**| Drawing Tool: Horizontal Line (`Alt+H`) & Rectangle Box (`R`) | `replay_drawings.js`, `replay.js` | **`[SELESAI / DONE 100%]`** |
| **`T-SIM-05B`**| Drawing Tool: Trendline (`T`) & Transient Ruler / Measure (`M`) | `replay_drawings.js` | **`[SELESAI / DONE 100%]`** |
| **`T-SIM-05C`**| Selection via `subscribeClick`, Move, Resize, Delete & Clear All | `replay_drawings.js`, `replay.js` | **`[SELESAI / DONE 100%]`** |
| **`T-SIM-06`** | Long & Short Position Box (Auto R:R, Lot, & Drag Handles) | `replay_simulator.js` | **`[SELESAI / DONE 100%]`** |
| **`T-SIM-07`** | Bar-by-Bar TP/SL Engine (Pessimistic Tie-Break & Manual Close) | `replay_simulator.js`, `replay_ledger.js` | **`[SELESAI / DONE 100%]`** |
| **`T-SIM-08`** | Storage Persistensi & Extension `verify_pure_replay.py` | `replay_storage.js`, `verify_pure_replay.py` | **`[SELESAI / DONE 100%]`** |

---

## 2. Rincian Tiket & Kriteria Penerimaan

### FASE 1: HUD Relocation & Visual Optimization (Prioritas Utama)

* **`T-SIM-01: Relocate HUD to Top-Left & Horizontal Compact Layout`**
  * **Target File:**
    - [`src/assistant/static/css/replay.css`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/src/assistant/static/css/replay.css#L506-L530)
    - [`src/assistant/templates/index.html`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/src/assistant/templates/index.html#L177-L216)
    - [`src/assistant/static/js/replay.js`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/src/assistant/static/js/replay.js#L470-L492)
  * **Status:** **`[SELESAI / DONE 100%]`** (Tervalidasi via CDP E2E)
  * **Tujuan:**
    Memindahkan floating HUD dari koordinat kanan atas (`top: 10px; right: 12px;`) ke pojok kiri atas (`top: 10px; left: 56px;`), serta mendesain ulang tata letak menjadi horizontal kompak agar lilin terbaru di sisi kanan kanvas 100% bebas dari halangan visual.
  * **Kriteria Penerimaan (Acceptance Criteria):**
    - [x] Posisi HUD berpindah ke kiri atas (`top: 10px; left: 56px;`) dengan ruang aman untuk toolbar vertikal sisi kiri.
    - [x] Desain diubah menjadi format horizontal kompak satu baris (OHLC, status playback, waktu UTC/lokal, dan spread range).
    - [x] Lilin terkini di ujung kanan grafik dan sumbu harga (*price scale*) tidak terhalang oleh HUD — **terukur**: `left: 57px, top: 11px`, HUD `right: 678px` vs plot `1444px` (desktop 1600×1000) dan `right: 669px` vs plot `730px` (fullscreen, breakpoint `≤860px` aktif).
    - [x] Fungsi render di `replay.js:470-492` (`renderHud`) memperbarui nilai DOM horizontal secara mulus.

* **`T-SIM-02: HUD Pointer-Events & Shortcut Toggle 'H'`**
  * **Target File:**
    - [`src/assistant/static/css/replay.css`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/src/assistant/static/css/replay.css#L522)
    - [`src/assistant/static/js/replay.js`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/src/assistant/static/js/replay.js#L614-L638)
    - [`src/assistant/templates/index.html`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/src/assistant/templates/index.html#L177-L183)
  * **Status:** **`[SELESAI / DONE 100%]`** (Tervalidasi via CDP E2E)
  * **Tujuan:**
    Mengatasi batasan `pointer-events: none` pada kartu HUD agar tombol interaktif (minimize toggle) dapat diklik, serta menambahkan shortcut keyboard `H` untuk menyembunyikan/menampilkan HUD secara instan.
  * **Kriteria Penerimaan:**
    - [x] Rule CSS diperbaiki: kontainer kartu `.replay-hud-floating` tetap tembus pandang/klik (`pointer-events: none;`), tetapi tombol aksi di dalamnya memiliki `pointer-events: auto;`.
    - [x] Tombol minimize (`—`) pada header HUD berfungsi menciutkan kartu menjadi pill ringkas.
    - [x] Menekan tombol keyboard `H` (saat tidak sedang fokus di elemen input/form) memicu toggle visibilitas HUD (`.is-hidden`) — diuji dengan `Input.dispatchKeyEvent` nyata, bukan `KeyboardEvent` sintetis, termasuk kasus fokus di `#replay-scrubber` yang harus **diabaikan**.
    - [x] Shortcut `H` tidak bertabrakan dengan shortcut yang sudah ada (Space, ArrowLeft, ArrowRight, F).
    - [ ] **Di luar scope Fase 1:** status hidden/minimized TIDAK dipersistensikan (reset saat reload). Jika dibutuhkan, tambahkan key keempat di Fase 5 — jangan anggap ini bug regresi.

---

### FASE 2: Left Vertical Toolbar & Canvas Overlay Architecture

* **`T-SIM-03: Vertical Tools Dock Component (Left Side Toolbar)`**
  * **Target File:**
    - `src/assistant/templates/index.html`
    - `src/assistant/static/css/replay.css`
    - `src/assistant/static/js/replay.js`
  * **Status:** **`[SELESAI / DONE 100%]`** (Tervalidasi via CDP E2E & Layout Engine)
  * **Tujuan:**
    Membangun komponen toolbar vertikal di sisi kiri kontainer grafik (`#replay-chart-wrap`) dengan lebar 48px, tema gelap serasi, dan sistem tooltip yang aman dari pemotongan kontainer (`overflow: hidden`).
  * **Kriteria Penerimaan:**
    - [x] Toolbar terpasang sebagai **flex child** di sisi kiri `#replay-chart-wrap` (`width: 48px`), sehingga kanvas chart menyusut dan tidak ada area plot yang tertutup. **Dilarang** `position: absolute; left: 0` (memblokir bar paling kiri + tooltip ter-clip oleh `overflow: hidden`).
    - [x] HUD pada breakpoint `≤ 860px` tetap memakai `left: 56px` agar tidak tertimpa dock (`z-index` dock > HUD).
    - [x] Memuat 8 tombol: Cursor (`V`), H-Line (`Alt+H`), Rect Box (`R`), Trendline (`T`), Ruler (`M`), Long Pos (`L`), Short Pos (`S`), Clear (`Del`).
    - [x] Tooltip mengambang ke arah kanan via `::after { content: attr(data-tooltip); left: calc(100% + 8px) }` pada setiap tombol; tidak menggunakan `title` native (menghindari tooltip ganda) dan tidak terpotong `overflow: hidden` karena dock adalah flex child, bukan overlay.
    - [x] Status tool aktif ditandai dengan kelas `.is-active` dan highlight biru `#2563eb`.
    - [ ] **Placeholder Fase 2:** tombol Clear (`Del`) dan shortcut `Delete`/`Backspace` sudah terpasang dan memanggil `onClearDrawings()`, tetapi penyimpanan gambar belum ada sehingga aksi ini belum menghapus apa pun. Implementasi nyata ada di **T-SIM-05C** — jangan dianggap bug regresi.

* **`T-SIM-04: HTML5 Canvas Overlay & Official Chart API Handle`**
  * **Target File:**
    - `src/assistant/static/js/replay_chart.js`
    - `src/assistant/static/js/replay_canvas.js` (Modul baru)
    - `tests/js/replay_canvas.test.js` (Unit test baru)
  * **Status:** **`[SELESAI / DONE 100%]`** (Tervalidasi via Node Test & CDP E2E; geometri/persistensi gambar menyusul di Fase 3)
  * **Tujuan:**
    Membuat layer `<canvas>` transparan di atas grafik dengan manajemen pointer-events dinamis dan mengekspos handle API resmi dari `replay_chart.js` (tanpa bergantung pada `SmcDebug.replay.getChart()`).
  * **Kriteria Penerimaan:**
    - [x] `replay_chart.js` mengekspos API publik resmi: `chartApi.getChart()`, `chartApi.getSeries()`, dan helper konversi koordinat (`timeToCoordinate`, `coordinateToTime`, `priceToCoordinate`, `coordinateToPrice`, `subscribeRange`, `subscribeClick`).
    - [x] Saat `tool === 'cursor'`, canvas overlay memiliki `pointer-events: none;` (interaksi pan/drag chart bawaan 100% tidak terganggu) dan listener overlay tidak melakukan `stopPropagation`.
    - [x] Saat `tool !== 'cursor'`, canvas overlay memiliki `pointer-events: auto;` serta `pointerdown` memanggil `stopPropagation()` + `setPointerCapture()` sehingga gesture pan `#replay-chart` tidak ikut ter-arm. Diuji E2E: press nyata pada canvas mode gambar menghasilkan 0 `pointerdown` di container, sedangkan mode cursor meneruskannya.
    - [x] Sinkronisasi redraw: `subscribeVisibleLogicalRangeChange` + event `controller.on('frame')` + watch signature skala harga (`coordinateToPrice(1)`) selama renderer terdaftar. Ketiganya memakai `requestRedraw()` terkoalesi per frame.
    - [ ] **Di luar scope Fase 2:** belum ada renderer terdaftar (canvas sengaja kosong) dan `subscribeClick` belum dikonsumsi. Geometri gambar, seleksi, dan rubber-band preview ada di **T-SIM-05A/05C**.

---

### FASE 3: Core Price Action Drawing Tools

* **`T-SIM-05A: Horizontal Line & Rectangle Box Tools`**
  * **Target File:** `src/assistant/static/js/replay_drawings.js`, `src/assistant/static/js/replay.js`
  * **Kriteria Penerimaan:**
    - [x] Handler keyboard di `replay.js:616` dimodifikasi agar kombinasi `Alt+H` diizinkan lewat ke tool H-Line.
    - [x] Tool H-Line (`Alt+H`): Klik pada chart menempatkan garis horizontal tak hingga pada level harga tertentu dengan label harga di sumbu kanan.
    - [x] Tool Rectangle (`R`): Klik-tarik atau klik 2 titik menempatkan zona kotak arsiran transparan (Order Block / Supply-Demand).
    - [x] Menampilkan *rubber-band preview* saat kursor digerakkan sebelum klik kedua.
    - [x] Jangkar waktu Rectangle di-*snap* ke bar terdekat yang sedang terlihat (`snapToRevealedBar`), sehingga kotak yang digambar di area kosong (whitespace sebelum bar pertama / sesudah bar terakhir) atau di celah data tetap punya `timeToCoordinate()` valid dan langsung terlihat setelah commit.

* **`T-SIM-05B: Trendline & Transient Ruler / Measure Tools`**
  * **Target File:** `src/assistant/static/js/replay_drawings.js`
  * **Kriteria Penerimaan:**
    - [x] Tool Trendline (`T`): Klik 2 titik menghubungkan garis tren diagonal dengan sudut derajat dan proyeksi.
    - [x] Tool Ruler (`M` atau `Shift + Klik`): Mengukur jarak pergerakan lilin dalam pips ($0.10/pip), nominal dollar, dan jumlah bar.
    - [x] Tool Ruler bersifat transien (hilang saat klik mouse berikutnya, tidak disimpan permanen di daftar gambar).
    - [x] Jangkar waktu Trendline memakai mekanisme *snap* yang sama (`snapToRevealedBar`), jadi garis tren yang dimulai di whitespace tidak lagi runtuh ke bar terakhir bulan (yang off-screen saat replay) dan tidak hilang setelah commit.

* **`T-SIM-05C: Object Selection via subscribeClick, Move, Delete & Clear All`**
  * **Target File:** `src/assistant/static/js/replay_drawings.js`, `src/assistant/static/js/replay.js`
  * **Kriteria Penerimaan:**
    - [x] Pada mode cursor, klik pada chart memicu `chart.subscribeClick()` untuk mendeteksi objek gambar di koordinat klik dan menandainya sebagai *selected*.
    - [x] Objek terpilih menampilkan titik kendali (*anchor handles*) yang dapat digeser untuk mengubah posisi atau ukuran.
    - [x] Menekan tombol `Delete` atau `Backspace` saat objek terpilih menghapus objek tersebut dari kanvas.
    - [x] Tombol Clear All di toolbar menghapus seluruh gambar aktif dengan dialog konfirmasi cepat.

---

### FASE 4: Interactive Strategy & Position Simulator Engine

* **`T-SIM-06: Long & Short Position Box (Risk/Reward Calculator)`**
  * **Target File:** `src/assistant/static/js/replay_simulator.js` (Modul baru)
  * **Kriteria Penerimaan:**
    - [x] Menempatkan kotak Long (`L`) atau Short (`S`) dengan garis Entry, batas SL (merah), dan target TP (hijau).
    - [x] Handle SL dan TP dapat digeser dengan mouse secara interaktif.
    - [x] Menggunakan formula finansial tervalidasi (§5.1):
      - Nominal Risk USD = $|\text{Entry} - \text{SL}| \times \text{Lot} \times 100$.
      - Nominal Reward USD = $|\text{TP} - \text{Entry}| \times \text{Lot} \times 100$.
      - Rasio R:R otomatis dikalkulasi dan ditampilkan pada kartu info ringkas **di luar kotak posisi** (gutter kiri; flip ke kanan bila kotak menempel tepi kiri), bukan di tengah kotak, agar zona TP/SL tidak tertutup. Ukuran kartu dibatasi (lebar efektif ±102px, tinggi 47px, font monospace 9px) dan tetap terbaca.
    - [x] Kartu info tidak menutupi body posisi: diverifikasi dari piksel kanvas nyata (bounding box kartu harus berada di kiri kotak, `card.right <= box.left - 2`).
    - [x] Kotak posisi sendiri dapat diproyeksikan setelah commit (jangkar waktu di-*snap* ke bar terlihat) dan tetap terlihat setelah ganti timeframe (interpolasi jangkar), sama seperti Rectangle/Trendline.
    - [x] Konfigurasi ukuran lot default `0.10 Lot` (dapat diubah trader, rentang sah `0.01`–`5.00` Lot; di luar rentang ditolak).

* **`T-SIM-07: Bar-by-Bar TP/SL Hit Engine & Paper Ledger Accounting`**
  * **Target File:** `src/assistant/static/js/replay_simulator.js`, `src/assistant/static/js/replay_ledger.js`
  * **Kriteria Penerimaan:**
    - [x] Menerapkan aturan resolusi matematis tervalidasi (§5.1):
      - **Pessimistic Tie-Break:** Jika High $\ge$ TP dan Low $\le$ SL pada satu bar, posisi dinyatakan **SL HIT (LOSS)**.
      - **Anti Look-Ahead:** Bar saat posisi dibuat dalam kondisi PAUSED tidak diikutsertakan dalam evaluasi TP/SL (evaluasi dimulai pada bar berikutnya).
      - **Manual Close:** Tombol / shortcut `C` menutup posisi seketika pada harga `candle.close`.
    - [x] Saldo simulasi compounding dihitung dari modal dasar $10.000 dengan potongan biaya spread riil ($0.20/oz).
    - [x] Modul ini terisolasi sepenuhnya dari modul legacy `replay_engine.js`.
    - [x] Evaluasi TP/SL terhubung ke event `frame` controller menggunakan `snapshot.candle` + `snapshot.index` (bukan field `cursor` yang tidak ada), sehingga hit terjadi saat playback/step, bukan hanya di unit test.
    - [x] Setiap TP/SL hit langsung memicu `syncStorage()` agar status posisi dan ringkasan ledger tidak hilang saat reload.
    - [x] Unit test matematis lulus 100% via `node --test tests/js/replay_simulator.test.js`.

---

### FASE 5: Data Persistence & E2E Automated Verification

* **`T-SIM-08: Cross-Timeframe LocalStorage & Extended verify_pure_replay.py`**
  * **Target File:** `src/assistant/static/js/replay_storage.js`, `scripts/verify_pure_replay.py`
  * **Kriteria Penerimaan:**
    - [x] Kunci penyimpanan berversi: `xauusd_replay_drawings_v1_{symbol}_{year}_{month:02d}`.
    - [x] Gambar S/R yang dibuat di M5 tetap muncul saat trader berganti ke M15 atau H1 pada bulan data yang sama.
    - [x] `scripts/verify_pure_replay.py` diperluas dengan pemeriksaan CDP baru (ambang mengikuti yang benar-benar ditegakkan, bukan ambang longgar):
      - HUD berada di kiri atas: `45px <= left <= 70px` dan `top <= 20px` (relatif terhadap `#replay-chart-wrap`).
      - HUD **tidak menyentuh price scale**: `hud.right <= plotWidth - 120` saat `plotWidth >= 1200`, atau `- 40` pada pane sempit.
      - HUD tetap satu baris kompak: `width <= 900px`.
      - Shortcut `H` diuji dengan `Input.dispatchKeyEvent` (bukan `KeyboardEvent` sintetis), termasuk kasus fokus di `#replay-scrubber` → HUD **tidak** boleh berubah.
      - Posisi HUD diukur ulang saat fullscreen (headless mengemulasi 800×600 sehingga breakpoint `≤860px` ikut teruji).
      - Memvalidasi keberadaan toolbar vertikal kiri dan aktivasi tombol alat.
    - [x] Seleksi objek diuji lewat **klik chart nyata** (`Input.dispatchMouseEvent`), tanpa fallback pemanggilan `handleChartClick()` langsung.
    - [x] Persistensi diuji end-to-end, bukan hanya keberadaan key:
      - Reload halaman memulihkan gambar, kotak posisi, saldo ledger, dan jumlah trade.
      - Ganti timeframe (M5 → M15) pada bulan yang sama mempertahankan gambar, posisi, dan ledger.
      - Ganti bulan (2026-10 → 2026-09) mengosongkan gambar/posisi dan mengembalikan ledger ke $10.000; kembali ke bulan asal memulihkan state-nya.
    - [x] TP/SL otomatis diuji lewat `frame` playback nyata: posisi tetap ACTIVE pada bar entry (anti look-ahead), lalu TP HIT pada bar berikutnya dan langsung tersimpan ke localStorage.
    - [x] Manual close diuji mengeksekusi `candle.close` bar aktif, bukan `entryPrice`.
    - [x] Regresi Rectangle/Trendline yang hilang setelah commit diuji: kotak digambar mulai dari area whitespace (`cx+100`), lalu dipastikan `timeToCoordinate(d.t1)` dan `timeToCoordinate(d.t2)` tidak `null` serta `t1 != t2`.
    - [x] Persistensi lintas timeframe diuji sampai level proyeksi piksel, bukan hanya jumlah objek: setelah M5 → M15, objek berjangkar waktu tetap menghasilkan *anchor handles* walau `timeToCoordinate()` mentah mengembalikan `null` untuk kedua jangkar (`exact: 0`, `projected: 1`).
    - [x] Visibilitas diuji langsung dari kanvas overlay, bukan hanya dari koordinat: piksel di dalam bounding box Rectangle yang di-*commit* harus non-transparan (`painted > 0`).
    - [x] Kartu info posisi (R:R/TP/SL) diuji dari piksel kanvas: komponen solid terbesar (kartu) harus berada di kiri kotak posisi (`card.right <= box.left - 2`) dengan ukuran ringkas (`w <= 170`, `h <= 60`).
    - [x] Seluruh suite `verify_pure_replay.py` (126 check saat ini) menghasilkan exit code 0 tanpa error di browser console.

---

### Catatan Verifikasi Reproduktif (Fase 3–5)

Perintah dan hasil yang benar-benar dijalankan pada repo ini:

| Suite | Perintah | Hasil |
| :--- | :--- | :--- |
| Node unit tests | `node --test tests/js/replay_canvas.test.js tests/js/replay_drawings.test.js tests/js/replay_engine.test.js tests/js/replay_simulator.test.js tests/js/replay_storage.test.js` | **57 / 57 PASS** |
| Backend + integrasi | `.venv\Scripts\python.exe -m pytest -q` | **119 passed** |
| End-to-end CDP | `.venv\Scripts\python.exe scripts/verify_pure_replay.py` | **126 PASS / 0 FAIL, exit 0** |

Catatan: `node --test tests/js/` (direktori) gagal pada Node 24; gunakan glob/file eksplisit seperti perintah di atas.
