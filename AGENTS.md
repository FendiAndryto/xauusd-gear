# AGENTS.md: Research Mission & Core Development Doctrine

Dokumen ini adalah **piagam hukum tertinggi (supreme mandate)** proyek riset trading robot scalping XAUUSD. Setiap agen AI (Antigravity/Claude/Gemini) yang beroperasi di repositori ini **WAJIB MEMATUHI** prinsip-prinsip di bawah ini tanpa pengecualian.

---

## 1. Misi Utama Penelitian (The Core Mission)

> **Membangun sistem robot trading kuantitatif XAUUSD otomatis yang mampu menghasilkan PROFIT MAKSIMAL YANG KONSISTEN DI SETIAP BULAN tanpa jeda, adaptif terhadap seluruh variasi struktur pasar riil, dan mempertahankan keunggulan matematis (*statistical edge*) yang sudah terbukti.**

---

## 2. Tiga Hukum Mutlak Penelitian (The Three Iron Laws)

### HUKUM 1: Pertahankan Alpha yang Sudah Menang (Preserve the Winning Edge)
* **Aturan:** DILARANG KERAS mengubah, mematikan, atau memangkas aturan yang terbukti menghasilkan profit besar di bulan-bulan yang sudah menang (contoh: Juli +$2.477 dan November +$1.056 pada baseline EXP-12).
* **Standar Kelulusan:** Setiap iterasi, upgrade, atau penambahan fitur baru **TIDAK BOLEH merusak atau mengurangi performa bulan-bulan yang sudah profit**. Jika sebuah eksperimen membuat bulan yang tadinya surplus berbalik menjadi minus, eksperimen tersebut **OTOMATIS GAGAL**.

### HUKUM 2: Adaptasi Struktur Pasar, BUKAN Pemotongan Kalender Statis (Market Structure Adaptation, Not Blind Time Pruning)
* **Aturan:** DILARANG KERAS menggunakan jalan pintas *overfitting* kalender statis (seperti mematikan hari tertentu secara total atau memblokir jam trading secara acak) untuk sekadar "menghijaukan" satu bulan yang kalah.
* **Proses Riset yang Benar:**
  1. Jika ada bulan tertentu yang belum profit (contoh: Oktober -$1.293 atau Agustus -$311), **lakukan audit forensik struktur market di bulan tersebut**:
     * Bagaimana volatilitas harian emas (Daily ATR & Range)?
     * Apa tipe struktur harganya (apakah *cascading trend*, *parabolic runaway expansion*, *high-frequency chop*, atau *trend pullback*)?
     * Mengapa posisi bot kalah (apakah posisi BUY terkena *falling knife*, atau SELL tertabrak ekspansi)?
  2. **Tingkatkan kecerdasan robot (*Structural & Regime Adaptation*)**: Buat logika deteksi struktur pasar dinamis yang mampu:
     * Mengenali kondisi pasar yang abnormal secara *real-time*.
     * Menyesuaikan parameter secara proporsional (*volatility-scaled boundaries*, konfirmasi *absorption/liquidity trap*, atau mengikuti arah tren).
     * Mengubah kondisi yang sebelumnya merugikan menjadi peluang profit baru, **TANPA mengubah aturan pada struktur normal di bulan-bulan yang sudah profit**.

### HUKUM 3: Validasi Menyeluruh Melintasi Seluruh Bulan (Continuous Multi-Month Audit)
* **Aturan:** Setiap evaluasi harus menguji performa secara kontinu melintasi seluruh rentang data tick riil institusional (53,54+ juta tick dari April s/d November 2026).
* **Tolak Pikir Parsial:** Keberhasilan tidak dinilai dari 1 bulan saja, melainkan dari **kemampuan robot menghasilkan net profit positif di SETIAP BULAN secara serempak** dengan *drawdown* terkendali.

---

## 3. Protokol Evaluasi Saat Menghadapi Bulan yang Belum Profit

Setiap kali bot mengalami kerugian di bulan tertentu, agen **WAJIB** menjalankan 4 langkah diagnostik ini:

1. **Forensik Arah Transaksi (BUY vs SELL Breakdown):**
   * Periksa sisi mana yang menjadi penyumbang kerugian terbesar (contoh: di Oktober, kerugian didominasi 70%+ oleh posisi BUY karena *cascading drop*).
2. **Karakterisasi Struktur Harga (Market Regime Fingerprinting):**
   * Hitung volatilitas, ukuran gelombang tren, kedalaman *pullback*, dan kecepatan ekspansi harga di bulan tersebut.
3. **Formulasi Hipotesis Struktural (Bukan Filter Waktu):**
   * Rancang mekanisme harga (contoh: *structural rejection filter*, *momentum absorption*, konfirmasi *higher-low/lower-high*) yang membedakan *false sweep* dari *true liquidity sweep*.
4. **Verifikasi Silang Anti-Regresi (Non-Regression Cross-Validation):**
   * Jalankan perubahan tersebut pada bulan-bulan pemenang (Juli & November). Jika profit Juli dan November turun, perbaiki formula adaptasi hingga profit Juli & November tetap utuh dan bulan yang rugi berhasil berbalik profit.

---

## 4. Status Target Akhir Riset (Definition of Master Completion)

Riset dinyatakan mencapai garis akhir (*production-ready state*) jika dan hanya jika:
- **Setiap bulan kalender** (April, Mei, Juni, Juli, Agustus, September, Oktober, November) mencatatkan **Net PnL POSITIF (+)** atau minimal terlindungi aman (*breakeven / near-zero loss* pada kondisi ekstrem).
- **Total Net PnL Kumulatif 8 Bulan:** Menghasilkan pertumbuhan modal yang konsisten (> +15% s/d +35%).
- **Max Drawdown Kumulatif:** Terkunci stabil di bawah 10% – 15%.
- **Higienis & Realistis:** Bebas dari anomali simulator (*multi-fill bursts*), memperhitungkan spread riil Exness dan latensi stochastic 50–120 ms.

---

## 5. Standar Baku Pelaporan Hasil Pengujian (Mandatory Reporting Standard)

Setiap agen AI yang menyajikan hasil pengujian/backtest di repositori ini **WAJIB SECARA TETAP** menyajikan 3 elemen laporan ini tanpa boleh diringkas atau dihilangkan:

1. **Tabel Ekuitas Berkelanjutan Bulanan (*Continuous Monthly Equity Carryover Table*):**
   * Menampilkan pergerakan saldo riil di mana modal akhir bulan sebelumnya menjadi modal awal bulan berikutnya (dimulai dari modal awal \$10.000 pada 1 April 2026).
   * Kolom wajib:
     - `Bulan Kalender`
     - `Modal Awal ($)`
     - `Net PnL ($)`
     - `Modal Akhir ($)`
     - `Return (%)`
     - `Max Drawdown (%)`
     - `Total Trade`
     - `Win Rate (%)`
     - `Profit Factor`
     - `Status Evaluasi` (PROFIT / PROTECTED / DEFICIT)
   * Baris ringkasan di bawah tabel:
     - `Modal Awal Portofolio` (\$10.000,00)
     - `Modal Akhir Portofolio`
     - `Total Net Profit Kumulatif ($ & %)`
     - `Max Drawdown Kumulatif 8 Bulan (%)`

2. **Tabel Rincian Arah Transaksi & Keterangan (BUY vs SELL Breakdown):**
   * Kolom wajib:
     - `Bulan`
     - `Total Trade`
     - `Trade BUY` & `PnL BUY ($)`
     - `Trade SELL` & `PnL SELL ($)`
     - `Keterangan Penyebab Profit / Loss` (Uraian penyebab mikro dan struktur pasar bulan tersebut)

3. **Audit Forensik Mendalam:**
   * Penjelasan konkret mengapa bulan yang profit bisa menang (faktor pemicu keunggulan).
   * Diagnosa ilmiah mengapa bulan yang minus mengalami kerugian (karakteristik volatilitas, tipe tren, arah dominan yang rugi) sesuai Protokol Bagian 3.
