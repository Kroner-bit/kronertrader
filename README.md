# 🚀 KronerTrader

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Engine: Backtesting.py](https://img.shields.io/badge/Engine-Backtesting.py-orange.svg)](https://kernc.github.io/backtesting.py/)

**KronerTrader** is a modular, high-performance algorithmic trading and quantitative research platform designed for forex and CFDs. It provides an end-to-end workflow: from high-resolution tick data acquisition and candle aggregation to rigorous backtesting, interactive visual reporting, realistic paper broker simulation, and a real-time live trading dashboard.

---

## 📑 Table of Contents

- [Key Features](#-key-features)
- [Architecture & Tech Stack](#-architecture--tech-stack)
- [Project Structure](#-project-structure)
- [Installation & Setup](#-installation--setup)
- [Quick Start Guide](#-quick-start-guide)
  - [1. Launch the Web Dashboard](#1-launch-the-web-dashboard)
  - [2. Download Historical Tick Data](#2-download-historical-tick-data)
  - [3. Run a Backtest via CLI](#3-run-a-backtest-via-cli)
  - [4. Run Forward-Testing in Terminal](#4-run-forward-testing-in-terminal)
- [Developing Custom Strategies](#-developing-custom-strategies)
- [API & WebSocket Endpoints](#-api--websocket-endpoints)
- [License & Disclaimer](#-license--disclaimer)

---

## ✨ Key Features

- **📥 High-Resolution Tick Data Downloader**
  - Automates historical tick data downloads from Dukascopy via `dukascopy-node`.
  - Automatic time-chunking and fault-tolerant ingestion.
  - Efficient storage into indexed SQLite tables (`market_data.db`).

- **⚡ High-Fidelity Backtesting Engine**
  - Powered by `backtesting.py`, `pandas`, and `numpy`.
  - Converts raw tick streams into custom candle timeframes (`1m`, `5m`, `15m`, `1h`, `1d`).
  - Computes standard quantitative metrics: Return %, Sharpe Ratio, Max Drawdown, Win Rate, and Trade Counts.
  - Generates standalone, interactive **Bokeh** HTML visualization reports.

- **💼 Realistic Paper Trading Broker**
  - Simulates an electronic broker locally (`PaperBroker`).
  - Supports demo accounts with multi-position management.
  - Realistic margin checks, position sizing, spreads, and slippage modeling.

- **🌐 Central Web Dashboard & REST API**
  - Built on **FastAPI** with WebSocket channels for live quotes and strategy updates.
  - Interactive web UI for inspecting account balances, open positions, instrument catalog, and strategy performance.
  - Automatic Swagger documentation at `/docs`.

- **🤖 Pluggable Strategy Framework**
  - Modular strategy architecture inheriting from `BaseStrategy`.
  - Pre-built reference strategies:
    - `ema_cross` — Exponential Moving Average Crossover.
    - `rsi_reversal` — Relative Strength Index Mean Reversion.
    - `timer_scalper` — High-Frequency 10s Long / 5s Close Timer Scalper.
  - Dynamic strategy loader (`strategies/loader.py`).

---

## 🛠 Architecture & Tech Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend & API** | Python 3.10+, FastAPI, Uvicorn, WebSockets, Pydantic |
| **Data Ingestion** | Node.js, `dukascopy-node`, SQLite3, Pandas |
| **Backtesting Engine** | `backtesting.py`, NumPy, Bokeh |
| **Frontend & UI** | Modern HTML5 / CSS3, Vanilla JS, Chart.js |

---

## 📂 Project Structure

```text
KronerTrader/
├── api/                     # FastAPI backend & WebSocket server
│   ├── __init__.py
│   └── server.py            # API routes, WebSocket hubs, and background jobs
├── backtesting_engine/      # Backtesting and performance calculation
│   ├── __init__.py
│   └── runner.py            # Candle resampling, backtesting.py integration, Bokeh reports
├── core/                    # Core trading & data infrastructure
│   ├── database.py          # SQLite connection, schema, and tick queries
│   ├── dukascopy_downloader.py # Python wrapper for dukascopy-node downloader
│   ├── instruments.py       # Instrument metadata & search catalog
│   └── paper_broker.py      # Simulated paper broker (orders, positions, accounts)
├── dashboard/               # Web Dashboard frontend
│   ├── static/              # CSS stylesheets, frontend JavaScript
│   └── templates/           # HTML templates (index.html)
├── data/                    # Market data store & instruments registry
│   ├── instruments.json     # Preloaded forex and CFD instrument profiles
│   └── market_data.db       # Local SQLite tick database (git-ignored)
├── reports/                 # Generated interactive Bokeh backtest reports (git-ignored)
├── scripts/                 # Node.js helper scripts for tick extraction
│   ├── extract_instruments.js
│   └── get_recent_ticks.js
├── strategies/              # Strategy library and live runners
│   ├── base_strategy.py     # Base abstract strategy class
│   ├── ema_cross.py         # EMA Cross strategy implementation
│   ├── rsi_reversal.py      # RSI Reversal strategy implementation
│   ├── timer_scalper.py     # 10s Long / 5s Close timer strategy
│   ├── live_runner.py       # Tick/bar loop runner for forward tests
│   ├── loader.py            # Dynamic strategy registry
│   └── run_strategy.py      # Standalone forward test CLI
├── .gitignore               # Ignored cache, databases, and environments
├── main.py                  # Unified CLI and application entrypoint
├── package.json             # Node.js dependencies (dukascopy-node)
└── requirements.txt         # Python dependencies
```

---

## 🚀 Installation & Setup

### Prerequisites

- **Python 3.10+**
- **Node.js 18+** & `npm`

### Step 1: Clone the Repository

```bash
git clone https://github.com/Kroner-bit/kronertrader.git
cd kronertrader
```

### Step 2: Python Virtual Environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install Dependencies

```bash
# Install Python packages
pip install -r requirements.txt

# Install Node.js dependencies (for tick downloader)
npm install
```

---

## 💻 Quick Start Guide

`main.py` provides a unified CLI for all operations.

### 1. Launch the Web Dashboard

Start the centralized API server and web interface:

```bash
python main.py server --host 127.0.0.1 --port 8000
```

- **Dashboard**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive Swagger Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 2. Download Historical Tick Data

Fetch tick data directly from Dukascopy into your local SQLite database:

```bash
python main.py download --symbol EURUSD --from-date 2025-01-01 --to-date 2025-03-01 --chunk-days 7
```

### 3. Run a Backtest via CLI

Run a backtest against your downloaded tick data:

```bash
python main.py backtest --strategy ema_cross --symbol EURUSD --timeframe 5m --cash 10000
```

Output includes Sharpe Ratio, Win Rate %, Total Return %, and an interactive HTML report saved under `reports/`.

### 4. Run Forward-Testing in Terminal

Simulate real-time execution in paper mode directly from your shell:

```bash
python main.py strategy --strategy ema_cross --symbol EURUSD --timeframe 1m --volume 0.1 --account demo_main
```

---

## 🧠 Developing Custom Strategies

Creating a new trading strategy is simple. Extend `BaseStrategy` in the `strategies/` folder:

```python
from strategies.base_strategy import BaseStrategy

class MyCustomStrategy(BaseStrategy):
    KEY = "my_custom_strategy"
    NAME = "My Custom Trend Strategy"

    def __init__(self, fast_period: int = 10, slow_period: int = 30):
        super().__init__()
        self.fast_period = fast_period
        self.slow_period = slow_period

    def on_bar(self, bar: dict, broker):
        """Called upon every newly formed bar/candle."""
        symbol = bar["symbol"]
        close_price = bar["close"]

        # Place orders through the broker instance:
        # broker.open_position(account_id="demo_main", symbol=symbol, side="BUY", volume=0.1)
        pass

    def on_tick(self, tick: dict, broker):
        """Called upon every incoming tick."""
        pass
```

Register the strategy in `strategies/loader.py` to make it accessible across the CLI, backtesting engine, and Web Dashboard.

---

## 📡 API & WebSocket Endpoints

When the server is running (`python main.py server`), the following key endpoints are available:

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/accounts` | `GET` | List all paper trading accounts and balances |
| `/api/instruments` | `GET` | Search and list available tradable instruments |
| `/api/data/coverage` | `GET` | View downloaded tick data date ranges & counts |
| `/api/data/download` | `POST` | Trigger asynchronous historical data downloads |
| `/api/backtest/run` | `POST` | Start a backtest and generate Bokeh visualization |
| `/api/backtest/reports`| `GET` | List and retrieve generated backtest reports |
| `/api/strategies` | `GET` | List all available registered strategies |
| `/api/strategies/start`| `POST` | Launch a live forward-testing strategy instance |
| `/ws/market` | `WebSocket`| Real-time tick and market price updates |

---

## 📜 License & Disclaimer

Distributed under the **MIT License**. See `LICENSE` for more information.

> **⚠️ Disclaimer**: This software is intended strictly for educational and research purposes. Algorithmic trading and CFD/Forex instruments involve substantial risk of financial loss. Past performance in backtests is not indicative of future market results. Always test thoroughly in a paper/demo environment before deploying any real capital.