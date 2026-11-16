# Doktrin & Piagam Penelitian Robot Trading XAUUSD
## Master Research Charter: Quantitative Scalping & Adaptive Market Regime Platform

**Status Dokumen:** Mandat Tertinggi Proyek (Immutable Project Charter)  
**Tujuan Proyek:** Pengembangan Robot Trading Kuantitatif Scalping Emas (`XAUUSDm`) Otomatis  
**Basis Pengujian:** 53.541.349 Tick Riil Broker Exness (April – November 2026, Latensi Stochastic 50–120 ms, Dynamic Spread, Zero Future Bias)  

---

## 1. Filosofi & Visi Dasar Proyek

Tujuan didirikannya proyek riset ini adalah **bukan sekadar membuat strategi yang profit di atas kertas atau menang di kondisi pasar tertentu saja**.

> **VISI SEJATI:**  
> **Membangun sistem robot kuantitatif yang mampu MENGHASILKAN PROFIT MAKSIMAL DI SETIAP BULAN secara konsisten.**  
> Robot ini harus memiliki kecerdasan struktural untuk beradaptasi dengan segala macam bentuk pasar emas:
> - Baik saat pasar berada dalam fase konsolidasi/sideway berombak rapi.
> - Maupun saat pasar mengalami reli tren satu arah yang ekstrem (*runaway expansion*), penurunan berundak (*cascading sell-off*), atau lonjakan volatilitas tak terduga.

---

## 2. Tiga Prinsip Mutlak Riset (Non-Negotiable Research Principles)

### Prinsip 1: Jangan Pernah Mengorbankan Bulan yang Sudah Menang (Preserve Proven Alpha)
Jika sebuah metode pada pengujian telah membuktikan kemampuannya menghasilkan profit besar di bulan-bulan tertentu (contoh: **Juli +$2.477** dan **November +$1.056** pada `EXP-12`), maka aturan dan kondisi dasar yang membuat bulan-bulan tersebut mencetak profit **TIDAK BOLEH DIBUANG ATAU DIHANCURKAN**.
* Segala bentuk pembaruan harus bersifat aditif (*enrichment*) atau kondisional (*adaptive switching*), bukan memangkas atau melemahkan mesin penghasil profit yang sudah ada.

### Prinsip 2: Evaluasi Berbasis Struktur Pasar, BUKAN Pemotongan Kalender Statis
Pendekatan mematikan bot secara membabi-buta pada hari tertentu (misal: "matikan hari Senin") atau jam tertentu (misal: "matikan jam 00:00-02:00 UTC") adalah bentuk **overfitting kalender statis**.
* Di pasar nyata, hari Senin atau jam pagi tidak selalu rugi. Kerugian terjadi karena **STRUKTUR HARGA** pada waktu tersebut sedang tidak cocok dengan metode dasar (misalnya sedang terjadi tren deras satu arah).
* **Solusi Sejati:** Mengajarkan robot membaca **karakteristik struktur market secara objektif** (volatilitas, kedalaman sweep, konfirmasi penolakan harga, divergensi momentum) sehingga robot secara dinamis tahu kapan harus *fading*, kapan harus *hold*, dan kapan harus *trend-following*.

### Prinsip 3: Mengubah Bulan Merugi Menjadi Sumber Keuntungan Baru
Jika ditemukan bulan-bulan yang masih merugi (contoh: Oktober -$1.293 atau Agustus -$311):
1. **Lakukan evaluasi mendalam:**
   * Mengapa strategi rugi di bulan tersebut?
   * Sisi mana yang kalah (BUY vs SELL)?
   * Bagaimana struktur pasar (rentang harian, kecepatan pergerakan, ada tidaknya retest)?
2. **Kembangkan logika penyesuaian (*Regime Adaptation*):**
   * Buat aturan adaptif yang membuat robot bisa **bertahan dan mencetak profit** di dalam struktur market yang di luar prediksi tersebut.
   * Pastikan aturan adaptif tersebut **TIDAK MERUBAH ATAU MERUSAK performa bulan lain yang sudah menghasilkan profit maksimal**.

---

## 3. Matriks Diagnosa Struktur Pasar Berdasarkan Uji Longitudinal (8 Bulan)

| Tipe Rezim Pasar | Contoh Bulan Riil | Karakteristik Struktur Emas | Perilaku Strategi Baseline | Arah Solusi Adaptif yang Tepat |
| :--- | :--- | :--- | :--- | :--- |
| **Clean Range Consolidation** | **Juli 2026, Nov 2026** | Emas bergerak dalam batas rentang $3–$10 teratur, sweep likuiditas langsung diikuti snapback cepat. | **PANEN PROFIT BESAR (+1.000$ s/d +2.400$)** terutama di sisi SELL. | **JAGA 100% INTACT.** Jangan ubah aturan ini! |
| **Cascading Trend Sell-Off** | **Oktober 2026** | Tren turun tajam berundak. Range Low terus ditembus ke bawah tanpa pantulan berarti. | **RUGI BESAR DI BUY (-$916)** karena bot berulang kali menangkap pisau jatuh. | **Konfirmasi Rejection Struktural:** Wajib ada kegagalan lower low (*absorption*) sebelum entri BUY, atau ikuti arah breakdown. |
| **Parabolic Runaway Bull Run** | **Agustus 2026** | Reli emas meledak +$678 dalam sebulan tanpa koreksi ke batas bawah. | Posisi SELL berulang kali tertabrak ekspansi tren atas. | **Deteksi Ekspansi Makro:** Matikan entri counter-trend SELL saat momentum makro berada dalam status *parabolic surge*. |
| **High Spread Puncak Rekor** | **April 2026, Mei 2026** | Emas di rekor tertinggi $4.889, broker melebarkan spread ke $0.31. | Bot memblokir order (0 trade, $0 loss) via filter spread $0.25. | **Pertahankan.** Proteksi friksi broker yang sangat efektif. |

---

## 4. Target Akhir (Definition of Success)

Pengembangan robot scalping XAUUSD dinyatakan sukses final jika:
1. **Konsistensi Bulanan Penuh:** Seluruh bulan pengujian (April–November) mencatatkan **Net PnL Hijau (Profit)** atau minimal *safe-breakeven*.
2. **Pertumbuhan Modal Bersih:** Menghasilkan pertumbuhan ekuitas kumulatif yang stabil dan maksimal di atas data tick riil broker.
3. **Maksimum Drawdown Terkendali:** Risiko *peak-to-trough drawdown* akun terkunci aman di bawah 10% – 15%.
