# 📊  pnl-dashboard

A lightweight Streamlit dashboard showing both **Today’s** and **Month-to-Date** Binance Futures PnL.

---

## 🚀 Features

- **Daily PnL** fetched live via Binance USDC-perpetual API  
- **Month-to-Date PnL** imported from a local Excel export (`~/Downloads/Export Trade History.xlsx`)  
- Token-level breakdown with fees and trade counts  
- Net PnL bar chart visualization  
- Manual refresh button for up-to-date data  
- Toggle between periods in the sidebar  

---
## 🔧 Prerequisites

- **Python** 3.10+  
- Binance API key & secret with USDC-perpetual permissions  
- Excel export file at `~/Downloads/Export Trade History.xlsx` with columns: 

---
## 📦 Installation

``` bash
git clone https://github.com/AlexBraguta/pnl-dashboard.git
cd pnl-dashboard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## ⚙️ Configuration

Create `credentials.py`:

``` bash
API_KEY    = "your_api_key"
API_SECRET = "your_api_secret"
```

Place `Export Trade History.xlsx` in `~/Downloads`.

## ▶️ Usage

``` bash
streamlit run main.py
```

Use the sidebar to toggle Today / Month-to-Date, then click Refresh Data.

## 📄 License
MIT © 2025