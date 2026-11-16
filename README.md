# XAUUSD Scalping Research Platform

Platform riset kuantitatif dan simulasi scalping presisi tinggi untuk komoditas Emas (`XAUUSDm`) berbasis data tick riil broker Exness (53,54+ juta tick).

> ### 🎯 Piagam & Doktrin Riset Utama (Research Charter)
> Proyek ini memiliki mandat mutlak: **Membangun robot trading otomatis yang menghasilkan profit maksimal secara konsisten di SETIAP BULAN tanpa jeda, adaptif terhadap seluruh variasi struktur pasar, serta mempertahankan alpha di bulan yang sudah menang.**
> 
> * Baca piagam agen: [`AGENTS.md`](AGENTS.md)
> * Baca dokumen visi penelitian: [`docs/RESEARCH_MISSION.md`](docs/RESEARCH_MISSION.md)
> * Buku besar eksperimen: [`docs/EXPERIMENT_REGISTRY.md`](docs/EXPERIMENT_REGISTRY.md)

## Fitur Utama
- **Real Tick Ingestion:** Penarikan data tick langsung dari MetaTrader 5 API dan parser CSV cepat via Polars.
- **High-Performance Storage:** Apache Parquet partitioned by `year=YYYY/month=MM` dengan kompresi ZSTD.
- **Reality Execution Simulator:**
  - Dynamic Spread (Ask untuk Buy, Bid untuk Sell)
  - Latency Queue (50 - 150 ms stochastic execution delay)
  - Dynamic & Stochastic Slippage Model
  - Komisi Broker ($6.00/lot round-turn)
- **Kuantitatif & Walk-Forward Analysis:**
  - Evaluasi Sharpe Ratio, Sortino Ratio, Profit Factor, Max Drawdown
  - WFA In-Sample vs Out-of-Sample anti-overfitting

## Setup Environment
Menggunakan Python 3.12 terisolasi dengan `uv`:
```bash
uv venv --python 3.12 .venv
.venv\Scripts\activate
uv pip install -e .
```
