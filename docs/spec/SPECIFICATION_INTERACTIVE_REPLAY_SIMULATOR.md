# SPESIFIKASI REKAYASA TEKNIS
## Interactive Strategy Simulator & Drawing Suite for XAUUSD Replay Terminal

**Dokumen ID:** `SPEC-SIM-REPLAY-01`  
**Status:** APPROVED / PATCHED & READY FOR EXECUTION  
**Kategori:** Web Interactive Simulation, Visual Charting & Paper Trading Suite  
**Target Platform:** Web Assistant Dashboard (`src/assistant/`)  
**Doktrin Tertinggi:** [`AGENTS.md`](file:///c:/Users/pendi/Repository/RESEARCH%20SCALPING/xauusd/AGENTS.md)

---

## 1. Latar Belakang & Visi Produk (Product Vision)

Replay Terminal XAUUSD saat ini telah berhasil menjalankan pemutaran lilin historis (*pure price action*) dengan mulus dan bebas lag melalui TradingView Lightweight Charts v4.2.3. Namun, terdapat dua kebutuhan pokok yang mendasari transformasi terminal ini:

1. **Eliminasi Obstruksi Visual Lilin Terkini (HUD Card Relocation):**
   Elemen Floating HUD saat ini berada di koordinat `top: 10px; right: 12px;` dengan `pointer-events: none` (`replay.css:508-522`). Karena pergerakan lilin terkini dan sumbu harga (*price scale*) berada di sisi kanan kanvas, kotak HUD ini menutupi formasi *high/wick* lilin terbaru ketika harga bergerak menguat naik (*bullish impulse*). Kotak ini harus direposisi ke area aman: **Pojok Kiri Atas (Top-Left)** dengan format yang lebih ramping, horizontal kompak, dan dilengkapi tombol minimize serta shortcut keyboard `H`.

2. **Transformasi dari Replay Pasif Menjadi Active Strategy Simulator (Paper Trading):**
   Latihan *price action* yang efektif membutuhkan interaksi dua arah:
   - Trader menandai level struktur penting (*Support/Resistance, Break of Structure, Order Block, Fair Value Gap*).
   - Trader mengeksekusi rencana trading secara simulasi (*Long/Short Position Box*) dengan batas Entry, Stop Loss, dan Take Profit.
   - Saat replay dimajukan batang demi batang (*bar-by-bar*), sistem mendeteksi secara deterministik apakah harga menyentuh TP atau SL, menghitung rasio *Risk-to-Reward* (R:R), menangani penutupan manual (*cut loss / take profit early*), serta merekam ledger performa (*Win Rate, Realized PnL, Floating PnL*).
   - **Pemisahan Modul Bersih:** Modul paper trading diimplementasikan sebagai subsistem mandiri (`replay_simulator.js` / `replay_ledger.js`), tanpa menumpang modul kalkulasi legacy `replay_engine.js`.

---

## 2. Kurasi Alat Gambar & Simulasi (Core Tools Curation)

Mengacu pada prinsip efisiensi Pareto (80/20), terminal membatasi diri pada **6 alat analisis & eksekusi inti** ditambah 2 fungsi utilitas kursor/manajemen kanvas (total 8 tombol di toolbar sisi kiri):

| Ikon / ID Tool | Kategori | Shortcut | Fungsi Teknis & Peruntukan |
| :---: | :--- | :---: | :--- |
| `cursor` | Utilitas | `V` / `Esc` | Mode interaksi default: memindahkan viewport chart (*pan*), zoom, dan memilih objek gambar via `chart.subscribeClick()`. |
| `hline` | Analisis | `Alt + H` | Menandai level Support/Resistance statis, Previous Day High/Low (PDH/PDL), dan garis Break of Structure (BOS / CHoCH). |
| `rect` | Analisis | `R` | Menandai area Order Block (OB), Supply & Demand Zone, Fair Value Gap (FVG), atau konsolidasi harga. |
| `trendline`| Analisis | `T` | Menandai garis tren, saluran likuiditas diagonal, dan garis kompresi harga. |
| `ruler` | Analisis | `Shift + Klik` / `M` | Penggaris ukur transien: mengukur jarak pergerakan harga instan dalam satuan **Pips**, **Nominal Dollar ($)**, dan **Jumlah Bar**. |
| `long_pos` | Simulasi | `L` | Kotak kalkulasi simulasi BUY: batas Entry, Stop Loss, Take Profit, kalkulasi otomatis rasio R:R, serta deteksi otomatis hit TP/SL saat replay berjalan. |
| `short_pos`| Simulasi | `S` | Kotak kalkulasi simulasi SELL: batas Entry, Stop Loss, Take Profit, kalkulasi otomatis rasio R:R, serta deteksi otomatis hit TP/SL saat replay berjalan. |
| `trash` | Utilitas | `Del` / `Backspace` | Menghapus objek terpilih atau membersihkan seluruh gambar pada kanvas aktif dengan konfirmasi. |

---

## 3. Arsitektur UI/UX & Tata Letak Kanvas (Layout Architecture)

```
+---------------------------------------------------------------------------------------------------------+
| HEADER: XAUUSD Replay Terminal | Status Koneksi MT5                                                    |
+---------------------------------------------------------------------------------------------------------+
| TOOLBAR ATAS: Mode Periode (Bulan/Rentang/Tahun) | Timeframe (M5/M15/H1) | [Muat Replay] [⛶ Fullscreen] |
+---------------------------------------------------------------------------------------------------------+
| TRANSPORT BAR: [⏮] [▶ Play / ⏸ Jeda] [⏭] | SPEED: [0.5x] [1x] [2x] [5x] [10x] [25x] [50x] [Max]         |
+---------------------------------------------------------------------------------------------------------+
| TIMELINE SCRUBBER: [══════════════════════════════●═══════════════════════] Bar 1.450 / 8.640          |
+-----+---------------------------------------------------------------------------------------------+-----+
| T   | [HUD KIRI ATAS: XAUUSD M5 | O: 2634.50 H: 2638.10 L: 2632.00 C: 2637.20 | 14:35 UTC] [—]  | P   |
| O   |                                                                                             | R   |
| O   |             ┌──────────────┐    ┌────────────────┐                                          | I   |
| L   |             │ ● ACTIVE BUY │    │  TP: 2650.00   │                                          | C   |
| B   |             │ R:R 1:2.00   │    ├────────────────┤                                          | E   |
| A   |  [OB/Rect]  │ TP +40p -20p │    │  ENTRY: 2635   │ ◄── [Lilin Terkini 100% Bebas Visual]    |     |
| R   |  ┌────────┐ │ PnL $+40/-$20│    ├────────────────┤                                          | S   |
|     |  └────────┘ └──────────────┘    │  SL: 2627.50   │                                          | C   |
| K   |   ─────────────────────────      └────────────────┘                                          | A   |
| I   |     [H-Line BOS]                                                                             | L   |
| R   |                                                                                             | E   |
| I   |                                                                   [⬇ Ikuti Lilin Terbaru]   |     |
+-----+---------------------------------------------------------------------------------------------+-----+
| STATUS BAR SIMULASI: Saldo Awal: $10.000 | Saldo Akun: $10.450 (+4.5%) | Posisi: 1 Active | [Close]      |
+---------------------------------------------------------------------------------------------------------+
```

> **Aturan tata letak kartu info posisi:** kartu R:R/TP/SL dirender **di gutter kiri kotak posisi** (bukan di tengah kotak) supaya zona TP dan SL tetap terlihat utuh. Bila kotak menempel tepi kiri viewport, kartu pindah otomatis ke kanan kotak. Kartu memakai font monospace 9px, lebar efektif ±102px, tinggi ±47px, dan dihubungkan ke kotak dengan garis putus-putus tipis.

### 3.1. Spesifikasi Relokasi & Desain Baru HUD
1. **Koordinat Posisi:**
   - Default: `top: 10px; left: 56px;` (menempel di sisi kiri atas dengan *offset* aman di sebelah kanan toolbar gambar selebar 48px). Nilai ini sudah diimplementasikan dan diverifikasi (`left: 57px, top: 11px` termasuk border).
   - Breakpoint `≤ 860px`: `top: 6px; left: 56px;` — **left wajib tetap ≥ 56px** agar tidak tertimpa dock (`z-index` dock lebih tinggi dari HUD) saat Fase 2 mendarat.
   - Z-Index: `10`.
   - Pointer-Events: Container utama tetap `pointer-events: none;`, namun seluruh elemen interaktif di dalamnya (tombol minimize `_`, tombol close) diberi `pointer-events: auto;`.
2. **Bentuk & Format:**
   - Desain horizontal kompak (satu baris data OHLC, status play, jam UTC/lokal).
   - Tombol toggle minimize (`—`) dan shortcut keyboard `H` (Hide/Show HUD).
   - Render HUD dikendalikan di `src/assistant/static/js/replay.js:475-492` (bukan di `replay_chart.js`).
3. **Batasan Fase 1:** status *hidden/minimized* bersifat per-sesi dan **tidak** dipersistensikan (reset setelah reload). Persistensi preferensi UI, jika diinginkan, masuk ke Fase 5 sebagai key storage keempat — bukan bagian dari AC Fase 1.

### 3.2. Spesifikasi Toolbar Sisi Kiri (Vertical Tools Dock)
1. **Dimensi & Posisi:**
   - Lebar tetap: `44px` hingga `48px`.
   - Posisi: **flex child** pertama di dalam `#replay-chart-wrap` (kontainer sudah `display:flex`), **bukan** `absolute`. Konsekuensi: kanvas chart menyusut selebar dock sehingga tidak ada lilin yang tertutup dan tidak ada area plot yang tidak bisa diklik/digambar.
   - Dilarang memakai `position: absolute; left: 0` untuk dock: pola itu menutupi ±48px area plot, memblokir bar paling kiri, dan membuat tooltip mustahil keluar dari `overflow: hidden` pada `.replay-chart-wrap` (`replay.css:483`).
   - **Tooltip** dirender sebagai pseudo-element `::after` pada tombol dengan `content: attr(data-tooltip)`, `position: absolute; left: calc(100% + 8px); top: 50%; transform: translateY(-50%)`, `z-index: 30`, muncul saat `:hover`/`:focus-visible`. Karena dock adalah flex child 48px, bubble melebar ke area chart di dalam `.replay-chart-wrap` dan tidak terpotong `overflow: hidden`.
2. **Keyboard Handler Pass-Through:**
   - Handler `onKeyDown` di `replay.js:616` dimodifikasi: **tidak** melakukan `return` langsung jika `event.altKey` aktif, melainkan memfilter secara spesifik agar `Alt + H` dapat diteruskan ke tool Horizontal Line.
   - Pengecekan `isTypingTarget` diekspos secara global/moduler agar shortcut satu huruf (`V`, `R`, `T`, `M`, `L`, `S`, `H`) tidak mencuri ketikan pengguna saat berada di input field.

---

## 4. Arsitektur Kanvas & Sinkronisasi Koordinat (Canvas Overlay Engine)

### 4.1. Pemecahan Masalah Pointer Events & Pan Navigation
Untuk menjaga agar navigasi bawaan Lightweight Charts (pan, drag histori, zoom roda mouse) tetap 100% mulus tanpa terblokir layer gambar:
1. **Saat Mode Cursor Aktif (`tool === 'cursor'`):**
   - Layer `<canvas id="replay-drawing-canvas">` diberi atribut CSS `pointer-events: none;`.
   - Seluruh event drag, mousedown, mousewheel jatuh langsung ke kanvas Lightweight Charts.
   - Seleksi objek gambar pada mode cursor memanfaatkan `chart.subscribeClick((param) => { ... })` yang membaca koordinat waktu dan harga klik, lalu mencocokkannya dengan batas bounding-box objek gambar terdekat.
2. **Saat Mode Menggambar Aktif (`tool !== 'cursor'`):**
   - Layer canvas overlay diberi `pointer-events: auto;` dengan kursor `crosshair`.
   - Event pointer ditangkap sepenuhnya oleh overlay: `pointerdown` memanggil `stopPropagation()` dan `setPointerCapture()`, sehingga listener gesture pan chart di `#replay-chart` (`replay_chart.js:115`) tidak ikut ter-arm. Tanpa ini, `dragOrigin`/`isPriceScaleDrag` tetap ter-set dan `pointerup` bisa memicu snap viewport saat user sedang menggambar.
   - Overlay mengekspos `canvasApi.onPointer(fn)` dengan payload `{type, x, y, time, price}` untuk konsumsi modul gambar (Fase 3).
   - Mode cursor tetap 100% passthrough: listener overlay tidak melakukan `stopPropagation` sama sekali.
   - Segera setelah objek selesai digambar (*committed*), mode otomatis kembali ke `cursor` (kecuali tombol *lock drawing mode* diaktifkan).

### 4.2. Kontrak Akses Chart Instance Resmi
Modul overlay gambar **dilarang keras** bergantung pada objek debug `global.SmcDebug.replay.getChart()`. 
`src/assistant/static/js/replay_chart.js` wajib mengekspos API publik resmi:
```javascript
chartApi.getChart();       // Instance IChartApi Lightweight Charts
chartApi.getSeries();      // Instance ISeriesApi (Candlestick Series)
chartApi.subscribeRange(); // Langganan perubahan logical range untuk redraw canvas
```
Redraw canvas overlay dipicu oleh tiga sumber:
1. `chart.timeScale().subscribeVisibleLogicalRangeChange()` untuk pan/zoom/pergeseran bar.
2. Event frame dari `controller.on('frame')` (di `replay.js`) untuk setiap langkah/lilin baru.
3. **Watch skala harga:** `subscribeVisibleLogicalRangeChange` **tidak** fire saat sumbu harga berubah (autoscale karena ekstrem baru, atau drag price scale). Selama minimal satu renderer terdaftar, `replay_canvas.js` menjalankan loop `requestAnimationFrame` yang membandingkan *signature* `coordinateToPrice(1)` dan memicu redraw hanya ketika nilainya berubah. Loop berhenti otomatis saat renderer terakhir di-unregister atau modul di-`destroy()`.
Semua redraw dikelola lewat `requestRedraw()` yang di-coalesce per frame `requestAnimationFrame` (tidak ada redraw ganda dalam satu frame).

### 4.3. Scoping & Persistensi Gambar Lintas Timeframe
Untuk mendukung tujuan latihan *price action*, gambar level teknikal (misal Support/Resistance yang digambar di M15) **harus tetap terlihat saat trader berpindah ke M5 atau H1** pada bulan data yang sama.
- **Kunci Penyimpanan (Storage Key):**
  `xauusd_replay_drawings_v1_{symbol}_{year}_{month:02d}`
- **Penyimpanan Berbasis Waktu & Harga Riil:**
  Setiap titik gambar disimpan dalam koordinat pasar absolut: `time` (epoch UTC detik) dan `price` (float presisi penuh). Saat timeframe berganti, kanvas cukup menghitung ulang proyeksi pikselnya melalui `timeToCoordinate()` dan `priceToCoordinate()`.
- **Normalisasi Jangkar Waktu (wajib):**
  `timeToCoordinate()` mengembalikan `null` untuk waktu yang bukan waktu bar (di tengah bar), waktu di masa depan (bar yang belum di-*reveal*), dan waktu di luar rentang terlihat. Karena itu jangkar `time` untuk Rectangle dan Trendline **tidak boleh** berupa nilai sintetis hasil `coordinateToTime()` mentah maupun fallback ke bar terakhir bulan. Saat `coordinateToTime()` mengembalikan `null` (klik di area whitespace atau di celah data), jangkar wajib di-*snap* ke bar terdekat yang **sedang terlihat** (rentang logis terlihat ∩ `0..watermark`) memakai `barSpacing`. Tanpa normalisasi ini, objek tersimpan dengan `time` yang tidak bisa diproyeksikan dan tidak pernah tergambar (gejala: kotak/garis tren "hilang" tepat setelah ditempatkan, sementara H-Line tetap tampil karena hanya memakai `price`).
- **Proyeksi Toleran Lintas Timeframe (wajib):**
  Jangkar waktu disimpan pada resolusi timeframe saat objek dibuat, sedangkan `timeToCoordinate()` hanya menerima waktu bar dari seri yang sedang aktif. Konsekuensinya, setelah berpindah timeframe (mis. M5 → M15) hampir semua jangkar menjadi "bukan waktu bar" dan proyeksi mengembalikan `null`. Modul gambar wajib menyediakan fallback interpolasi: cari dua bar aktif yang mengapit `t`, lalu interpolasi linear posisi piksel di antara `logicalToCoordinate(i-1)` dan `logicalToCoordinate(i)` berdasarkan rasio waktu. Tanpa lapisan ini, objek tetap tersimpan (jumlahnya benar) tetapi tidak tergambar — persis gejala "hilang setelah ganti timeframe".

---

## 5. Mesin Simulasi Strategi & Paper Trading (Simulation Engine)

### 5.1. Penutupan Blocker Spesifikasi Matematis (Blockers B1, B2, B3)

#### [B1] Ukuran Lot & Rumus Dimensi Finansial
* **Spesifikasi Kontrak XAUUSD:** 1 Lot Standar = 100 Troy Ounce (oz).
* **Konfigurasi Default:** Lot simulasi = `0.10 Lot` (dapat diubah trader: 0.01 s/d 5.0 Lot).
* **Spread Cost Default:** `$0.20` per oz ($20 per 1.0 lot round-turn).
* **Formula Perhitungan Benar:**
  $$\text{Pergerakan Harga (\$/oz)} = \begin{cases} \text{Exit Price} - \text{Entry Price} & (\text{BUY / Long}) \\ \text{Entry Price} - \text{Exit Price} & (\text{SELL / Short}) \end{cases}$$
  $$\text{Gross PnL (\$)} = \text{Pergerakan Harga} \times \text{Lot} \times 100$$
  $$\text{Net PnL (\$)} = \text{Gross PnL} - (\text{Spread Cost} \times \text{Lot} \times 100)$$
  $$\text{Risk USD (\$)} = |\text{Entry} - \text{SL}| \times \text{Lot} \times 100$$
  $$\text{Reward USD (\$)} = |\text{TP} - \text{Entry}| \times \text{Lot} \times 100$$
  $$\text{R:R Ratio} = \frac{|\text{TP} - \text{Entry}|}{|\text{Entry} - \text{SL}|}$$

#### [B2] Jalur Keluar Manual (Manual Position Close / Cut Loss)
* Menyediakan aksi **"Close Position"** instan via tombol di status bar simulasi atau shortcut keyboard `C`.
* Ketika posisi ditutup manual, harga keluar (*Exit Price*) dipatok pada harga penutupan lilin aktif (`candle.close`), posisi ditutup seketika, dan PnL direalisasikan ke ledger saldo akun.

#### [B3] Resolusi Ambiguasi Bar-by-Bar
1. **Kasus TP dan SL Tersentuh di Lilin yang Sama:**
   Jika pada satu lilin $High \ge TP$ dan $Low \le SL$:
   **Aturan Konservatif (Pessimistic Execution):** Posisi dinyatakan **SL HIT (LOSS)** untuk menjaga integritas pengujian risiko trading yang disiplin dan anti-overfitting.
2. **Look-Ahead Prevention (Posisi Dibuat di Tengah Lilin Paused):**
   Jika trader memasang posisi saat replay sedang PAUSED pada bar $N$, lilin bar $N$ **tidak** diikutsertakan dalam pemeriksaan TP/SL. Evaluasi pertama baru dimulai ketika replay melangkah ke bar $N+1$ (mencegah *hindsight bias*).
3. **Aturan Overlap:**
   Secara default, simulator beroperasi dalam mode **Single Position** (hanya 1 trade aktif dalam satu waktu). Jika trader membuat posisi baru saat masih ada trade berjalan, simulator menutup posisi lama secara otomatis pada harga `candle.close` bar aktif (bukan pada harga entry), lalu mencatatnya ke ledger sebagai `MANUAL_CLOSE` sebelum posisi baru dipasang.

---

## 6. Persistensi Data & Skema Ledger

Penyimpanan data lokal di browser menggunakan 3 kunci terpisah berversi:
1. `xauusd_replay_drawings_v1_{symbol}_{year}_{month:02d}`: Array gambar struktural (H-Line, Rectangle, Trendline).
2. `xauusd_replay_positions_v1_{symbol}_{year}_{month:02d}`: Array posisi simulasi (Long/Short boxes beserta state aktif/closed).
3. `xauusd_replay_ledger_v1_{symbol}_{year}_{month:02d}`: Ringkasan saldo awal ($10.000), saldo akhir, daftar trade tertutup, dan metrik performa.

Format `month:02d` adalah satu-satunya format yang sah (contoh: `xauusd_replay_drawings_v1_XAUUSD_2026_10`) dan harus dipakai konsisten oleh `replay_storage.js` serta test.

**Semantik pemulihan (restore):**
- Saat payload bulan dimuat, state dibaca dari kunci simbol+bulan tersebut **sebelum** controller mempublikasikan frame pertama, sehingga posisi bulan lama tidak pernah dievaluasi terhadap lilin bulan baru.
- Bila kunci bulan tujuan belum ada, daftar gambar dan posisi di-reset ke kosong dan ledger dikembalikan ke modal awal $10.000. Tidak ada objek yang bocor lintas bulan.
- Ringkasan ledger (saldo, peak equity, max drawdown, dan daftar trade tertutup) ikut dipulihkan; reload tidak mengembalikan saldo ke $10.000 selama posisi masih ada di kunci bulan yang sama.

**Pemicu persistensi:** pembuatan objek, selesai move/resize (pointerup), Delete/Clear, manual close (`C`), dan setiap TP/SL hit yang dihasilkan evaluasi bar-by-bar.
