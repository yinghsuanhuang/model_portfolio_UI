# Project Codebase Documentation

## Overview
This project is a **Quantitative Model Portfolio Research Platform**. It allows users to build, backtest, and analyze multi-asset portfolios using advanced optimization techniques (Markowitz Mean-Variance, Sortino Ratio) consistent with institutional research methodologies.

## Core Capabilities
*   **Dynamic Backtesting:** Simulates realistic portfolio performance over time with rolling rebalancing (Monthly, Quarterly, Annually).
*   **Portfolio Optimization:** Automatically calculates optimal asset weights to maximize risk-adjusted returns (Sharpe, Sortino, or Utility).
*   **Custom Return Models:** Uses fundamental data (Earnings Growth, PE, Yields) rather than simple historical averages to forecast returns.
*   **Interactive Analysis:** Provides a web-based dashboard (Streamlit) for visualizing NAV curves, drawdowns, and weight allocation changes.

## Modeling Logic & Algorithms

### 1. Expected Return Model (`engine/return_model.py`)
Instead of using simple historical averages, the system builds "Forward-Looking" return expectations:
*   **Equities (Stocks):**
    *   **Formula:** $E[R] = \text{Growth} + \text{Dividend Yield} + \text{Valuation Adjustment}$
    *   **metrics:**
        *   *Growth*: 5-Year annualized EPS growth.
        *   *Valuation*: Mean-reversion of PE ratio (comparing current PE to 5-year average).
*   **Fixed Income (Bonds):**
    *   **Formula:** $E[R] \approx \text{YTM} - \text{Duration} \times (\text{Forecast Yield} - \text{Current Yield})$
    *   Uses Yield-to-Maturity and Duration to estimate returns based on interest rate forecasts.
*   **Industries / Sectors:**
    *   Uses **CAPM** (Capital Asset Pricing Model) to estimate returns based on the sector's Beta relative to the S&P 500.

### 2. Risk Model (`engine/risk_model.py`)
*   **Covariance Matrix:** Estimates how assets move together.
*   **Method:** Uses **Ledoit-Wolf Shrinkage** (default). This is more robust than a standard sample covariance matrix, reducing estimation error in cases where history is short or noisy.

### 3. Optimization Algorithm (`engine/optimizer.py`)
The engine solves for the optimal weights $w$ to maximize a specific objective function, subject to constraints:
*   **Objective Functions:**
    *   **Max Sharpe:** Maximize $\frac{w^T \mu}{\sqrt{w^T \Sigma w}}$
    *   **Max Sortino:** Maximize return relative to *downside deviation* (minimizing bad volatility only).
    *   **Max Utility:** Maximize $w^T \mu - \frac{\lambda}{2} w^T \Sigma w$ (balancing return vs. risk aversion).
*   **Constraints:**
    *   **Long Only:** $0 \le w_i \le \text{Upper Limit}$ (no short selling).
    *   **Fully Invested:** $\sum w_i = 1$ (optional/implied).
    *   **Group Limits:** Maximum allocation for Stocks vs. Bonds.

### 4. Backtest Engine (`engine/backtest.py`)
*   **Rolling Window Approach:**
    1.  At each rebalance date $t$, look back $N$ months (Lookback Window).
    2.  Calculate $\mu$ (Expected Returns) and $\Sigma$ (Covariance) using data up to $t$.
    3.  Run Optimizer to find new weights $w_{t+1}$.
    4.  Simulate holding these weights for the next period, accounting for market price changes (Drift).
    5.  Repeat until the end date.

---

## File Structure & Details

### Root Directory

### `main.py`
**Feature:** Core Entry Point & Pipeline Orchestrator
**Description:**
- **Entry Point:** The main script to run the backend verification or CLI process.
- **Pipeline:** Contains `run_full_pipeline_markowitz`, which orchestrates the entire backtest loop:
    1.  Loads data.
    2.  Iterates month-by-month.
    3.  Calls `return_model`, `risk_model`, and `optimizer` to calculate weights.
    4.  Runs performance analysis using `run_all_frequencies_monthly`.
- **UI Support:** Provides `run_ui_pipeline` for the Streamlit app to execute backtests on demand.
- **Output:** Saves weights, returns, and summary statistics to the `outputs/` directory.

### `ui/app.py`
**Feature:** Streamlit Web Interface
**Description:**
- **Dashboard:** Generates the interactive web dashboard for users.
- **Configuration:** Allows users to adjust backtest parameters (Rebalance frequency, Objective, Lookback windows, Constraints) via the sidebar.
- **Visualization:** Displays:
    1.  Performance Tables (CAGR, Sharpe, Sortino, MDD, etc.).
    2.  Interactive Charts (NAV curves, Returns).
    3.  Weight Analysis (Current vs. Historical weights).
- **Integration:** Calls `main.py`'s `run_ui_pipeline` to execute the backend logic dynamically.

### `config.yaml`
**Feature:** Global Configuration
**Description:**
- **Settings:** Centralized configuration file for the entire project.
- **Sections:**
    - `project`: Timezone, return calculation methods.
    - `paths`: Locations of data files.
    - `universe`: Definitions of asset lists (Markets, Industries, Bonds) and Benchmark columns.
    - `dates`: Backtest start/end dates.
    - `schedule`: Rebalancing frequency rules.
    - `risk`: Risk model parameters (Lookback, Covariance method).
    - `return_model`: Rolling windows for growth/PE metrics.
    - `constraints`: Asset allocation limits (Lower/Upper bounds).
    - `optimizer`: Optimization targets (Sortino/Sharpe/Utility) and parameters.
    - `backtest`: Trading costs and Risk-free rate.

### `debug_nb_vs_pipeline.py`
**Feature:** Debugging Tool (Notebook vs Pipeline)
**Description:**
- **Verification:** A specialized script to compare the Python pipeline's results against original Jupyter Notebook outputs (if available).
- **Diagnostics:**
    - Checks for `NaN` values in returns or weights.
    - Aligns time indices (month-end).
    - Calculates absolute differences between pipeline and notebook results value-by-value.
    - Helps identify discrepancies in data loading or calculation logic.

### `README.md`
**Feature:** Project Documentation
**Description:**
- Contains project instructions, setup guides, or general information (assumed standard usage).

### `requirements.txt`
**Feature:** Dependency List
**Description:**
- Lists all Python packages required to run the project (e.g., `pandas`, `streamlit`, `matplotlib`, `pypfopt`, `scikit-learn`, `statsmodels`).

---

## Engine Directory (`engine/`)
The core logic library for the quantitative models.

### `engine/data_loader.py`
**Feature:** Data Ingestion & Preprocessing
**Description:**
- **Loading:** Reads Excel files (`.xlsx`) specified in `config.yaml`.
- **Cleaning:**
    - Resamples all data to month-end frequency (`resample("M").last()`).
    - Standardizes column names (e.g., renaming specific raw columns to generic "Price").
- **Structure:**
    - `load_market_sheet`: Loads equity market data.
    - `load_benchmark`: Loads benchmark indices.
    - `load_bond_and_industry`: Loads bond and industry sector data.
    - `load_all_data`: Aggregates all sources into a single dictionary for valid access.

### `engine/return_model.py`
**Feature:** Expected Return Estimation (Bootstrap / Fundamental)
**Description:**
- **Logic:** implements the custom expected return logic used in the original Notebooks.
- **Equity:** Calculates expected return based on:
    - **Growth Rate:** 5-year annualized EPS growth (with safeguards for short data).
    - **Dividend Yield:** 12-month average.
    - **Valuation Adjustment:** Mean reversion of PE ratio.
- **Bonds:** Calculates Expected Return using Yield-to-Maturity (YTM), Duration, and Rate Forecasts.
- **Industries:** Uses CAPM Beta relative to the S&P 500 to estimate returns.
- **Output:** Returns the vector of Expected Returns (`mu`) and historical return series for risk calculation.

### `engine/risk_model.py`
**Feature:** Risk / Covariance Matrix
**Description:**
- **Covariance:** Calculates the covariance matrix (`Sigma`) of asset returns.
- **Methods:**
    - `sample`: Standard sample covariance.
    - `ledoitwolf`: Shrinkage estimator (Ledoit-Wolf) for better stability used by default.
- **Adjustment:** Applies annualization factors to the matrix.

### `engine/optimizer.py`
**Feature:** Portfolio Optimization (MVO)
**Description:**
- **Solver:** Uses `PyPortfolioOpt` (`pypfopt`) to find optimal weights.
- **Objectives:** Supports multiple optimization goals defined in config:
    - `sharpe`: Maximize Sharpe Ratio.
    - `sortino`: Maximize Sortino Ratio (via Mean-Semivariance).
    - `utility`: Maximize Quadratic Utility.
- **Constraints:** Applies L2 regularization and Min/Max weight limits per asset and asset class.

### `engine/backtest.py`
**Feature:** Backtesting Logic
**Description:**
- **Simulation:** Runs the monthly time-step simulation of the portfolio.
- **Trading:** Simulates a realistic trading environment:
    - Aligning weights to next-month returns.
    - Calculating transaction costs (bps).
    - Tracking Portfolio NAV (Net Asset Value).
- **Drift:** Simulates "Buy and Hold" within rebalancing periods (weights drift with price changes).
- **Statistics:** Calculates performance metrics: Total Return, CAGR, Sharpe, Sortino, MDD, Calmar Ratio.
- **Modes:** Includes logic for different rebalancing schedules (Monthly `M`, Quarterly `Q`, Annual `A`, etc.).

### `engine/config.py`
**Feature:** Configuration Helper
**Description:**
- **Utility:** Simple helper function `load_config` to read and parse the `config.yaml` file safely.

### `engine/constraints.py`
**Feature:** Constraint Helpers
**Description:**
- **Indices:** Helper function `build_stock_type_indices` to identify which assets belong to specific groups (e.g., Stocks vs. Bonds) for applying group-level constraints in the optimizer.

### `engine/utils.py`
**Feature:** General Utilities
**Description:**
- **Math:** Helper functions for return calculations, such as `period_returns` (calculating percentage change or log returns).
