from credentials import API_KEY, API_SECRET
from binance.um_futures import UMFutures
from datetime import datetime, timezone
from binance.error import ClientError
import streamlit as st
import altair as alt
import pandas as pd
import warnings
import os
import glob

# Suppress openpyxl "no default style" warning
warnings.filterwarnings("ignore", "Workbook contains no default style", UserWarning)

# Initialize Binance Futures client
client = UMFutures(API_KEY, API_SECRET)


def get_all_symbols() -> list[str]:
    """Get all perpetual USDC symbols from Binance."""
    try:
        info = client.exchange_info()
        return [s["symbol"]
                for s in info["symbols"]
                if s.get("contractType") == "PERPETUAL" and s["symbol"].endswith("USDC")]
    except ClientError as error:
        st.error(f"Failed to fetch symbols: {error}")
        return []


def get_trades_since(start_time_ms: int) -> list[dict]:
    """Fetch trades from Binance API since start_time_ms."""
    trades: list[dict] = []
    symbols = get_all_symbols()

    if not symbols:
        st.warning("No symbols found or API error occurred.")
        return trades

    progress_bar = st.progress(0)
    for i, symbol in enumerate(symbols):
        try:
            symbol_trades = client.get_account_trades(
                symbol=symbol,
                startTime=start_time_ms,
                recvWindow=6000
            )
            trades.extend(symbol_trades)
        except ClientError as error:
            if "No permission" not in str(error):  # Suppress permission errors for cleaner output
                st.warning(f"Failed to fetch trades for {symbol}: {error}")

        progress_bar.progress((i + 1) / len(symbols))

    progress_bar.empty()
    return trades


def find_excel_file() -> str:
    """Find the Excel file in Downloads folder."""
    downloads_path = os.path.expanduser("~/Downloads")

    # Try multiple possible filenames
    possible_names = [
        "Export Trade History.xlsx",
        "export trade history.xlsx",
        "Export_Trade_History.xlsx",
        "TradeHistory.xlsx",
        "trade_history.xlsx"
    ]

    for name in possible_names:
        file_path = os.path.join(downloads_path, name)
        if os.path.exists(file_path):
            return file_path

    # If exact names not found, search for any Excel file with "trade" or "history"
    excel_files = glob.glob(os.path.join(downloads_path, "*.xlsx"))
    for file_path in excel_files:
        filename = os.path.basename(file_path).lower()
        if "trade" in filename or "history" in filename:
            return file_path

    return ""


def get_trades_from_file(start_datetime: datetime) -> list[dict]:
    """Load trades from Excel file."""
    if start_datetime.tzinfo is not None:
        start_datetime = start_datetime.astimezone(timezone.utc).replace(tzinfo=None)

    file_path = find_excel_file()
    if not file_path:
        st.error("Excel file not found in ~/Downloads. Please ensure the trade history file is downloaded.")
        return []

    st.info(f"Reading file: {os.path.basename(file_path)}")

    try:
        # Try different sheet names and structures
        df = pd.read_excel(file_path, parse_dates=["Date(UTC)"])

        # Check if required columns exist
        required_cols = ["Date(UTC)", "Symbol", "Realized Profit", "Fee"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            st.error(f"Missing required columns in Excel file: {missing_cols}")
            st.info(f"Available columns: {list(df.columns)}")
            return []

    except Exception as e:
        st.error(f"Failed to read Excel file: {e}")
        return []

    # Normalize numeric columns (strip leading ' if present)
    num_cols = ["Price", "Quantity", "Amount", "Fee", "Realized Profit"]
    for col in num_cols:
        if col in df.columns:
            df[col] = (df[col]
                       .astype(str)
                       .str.lstrip("'")
                       .str.replace(",", "")  # Remove thousand separators
                       .replace(["", "nan", "None"], "0")
                       .pipe(pd.to_numeric, errors="coerce")
                       .fillna(0))

    # Filter by date
    #df = df[df["Date(UTC)"] >= start_datetime]

    if df.empty:
        st.warning("No trades found in Excel file")
        return []

    trades: list[dict] = []
    for _, row in df.iterrows():
        trades.append({
            "symbol": row["Symbol"],
            "realizedPnl": float(row["Realized Profit"] or 0),
            "commission": float(row["Fee"] or 0),
            "commissionAsset": row.get("Fee Coin", "USDC")  # Default to USDC if not specified
        })

    return trades


def get_price(symbol: str) -> float:
    """Get current price for a symbol."""
    try:
        ticker = client.ticker_price(symbol=symbol)
        return float(ticker["price"])
    except ClientError as error:
        st.warning(f"Failed to get price for {symbol}: {error}")
        return 1.0  # Return 1.0 instead of 0.0 to avoid division by zero


def calculate_token_pnl(trades: list[dict]) -> pd.DataFrame:
    """Calculate PnL analysis for each token."""
    if not trades:
        return pd.DataFrame()

    bnb_price = get_price("BNBUSDC")
    if bnb_price == 0:
        bnb_price = 600.0  # Fallback price
        st.warning("Using fallback BNB price of $600")

    data: dict[str, dict] = {}

    for trade in trades:
        sym = trade["symbol"]
        realized = float(trade["realizedPnl"])
        commission = float(trade["commission"])
        asset = trade["commissionAsset"]

        if sym not in data:
            data[sym] = {
                "realized_pnl": 0.0,
                "bnb_fees": 0.0,
                "usdc_fees": 0.0,
                "trades": 0
            }

        data[sym]["realized_pnl"] += realized
        data[sym]["trades"] += 1

        if asset == "BNB":
            data[sym]["bnb_fees"] += commission
        elif asset in ("USDC", "USDT"):
            data[sym]["usdc_fees"] += commission

    rows: list[dict] = []
    for sym, vals in data.items():
        bnb_fees_usdc = vals["bnb_fees"] * bnb_price
        total_fees = bnb_fees_usdc + vals["usdc_fees"]
        net_pnl = vals["realized_pnl"] - total_fees

        rows.append({
            "Token": sym,
            "Realized PnL": round(vals["realized_pnl"], 2),
            "BNB Fees": round(vals["bnb_fees"], 5),
            "BNB Fees (USDC)": round(bnb_fees_usdc, 2),
            "Direct USDC Fees": round(vals["usdc_fees"], 2),
            "Total Fees (USDC)": round(total_fees, 2),
            "Net PnL": round(net_pnl, 2),
            "Trades": vals["trades"]
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        # Sort by Net PnL descending
        df = df.sort_values("Net PnL", ascending=False)

        # Add total row
        total = {
            "Token": "TOTAL",
            "Realized PnL": round(df["Realized PnL"].sum(), 2),
            "BNB Fees": round(df["BNB Fees"].sum(), 5),
            "BNB Fees (USDC)": round(df["BNB Fees (USDC)"].sum(), 2),
            "Direct USDC Fees": round(df["Direct USDC Fees"].sum(), 2),
            "Total Fees (USDC)": round(df["Total Fees (USDC)"].sum(), 2),
            "Net PnL": round(df["Net PnL"].sum(), 2),
            "Trades": int(df["Trades"].sum())
        }
        df = pd.concat([df, pd.DataFrame([total])], ignore_index=True)

    return df


def create_pnl_chart(df: pd.DataFrame):
    """Create PnL visualization chart."""
    df_chart = df[df["Token"] != "TOTAL"].copy()
    if df_chart.empty:
        return None

    # Sort by Net PnL for better visualization
    df_chart = df_chart.sort_values("Net PnL", ascending=True)

    return (
        alt.Chart(df_chart)
        .mark_bar()
        .encode(
            x=alt.X("Net PnL:Q", title="Net PnL (USDC)"),
            y=alt.Y("Token:N", sort=alt.EncodingSortField(field="Net PnL", order="ascending")),
            color=alt.condition(
                alt.datum["Net PnL"] > 0,
                alt.value("#00ff00"),  # Green for positive
                alt.value("#ff0000")  # Red for negative
            ),
            tooltip=[
                "Token",
                alt.Tooltip("Net PnL:Q", format=".2f"),
                alt.Tooltip("Realized PnL:Q", format=".2f"),
                alt.Tooltip("Total Fees (USDC):Q", format=".2f"),
                "Trades"
            ]
        )
        .properties(
            title="Net PnL by Token",
            width=600,
            height=max(300, len(df_chart) * 25)
        )
    )


def highlight_total_and_negative(row):
    """Style the dataframe: bold TOTAL row, red for negative PnL."""
    styles = [""] * len(row)

    if row["Token"] == "TOTAL":
        styles = ["font-weight: bold"] * len(row)

    # Color negative Net PnL in red
    if row["Net PnL"] < 0:
        styles[6] = "color: red"  # Net PnL column index

    return styles


def main():
    """Main Streamlit application."""
    st.set_page_config(page_title="Trading PnL Analysis", layout="wide")

    # Sidebar
    st.sidebar.title("Trading PnL Analyzer")
    page = st.sidebar.radio("Select Period", ["Today", "Month-to-Date"])

    if st.sidebar.button("🔄 Refresh Data"):
        st.rerun()

    # Main content
    now = datetime.now(timezone.utc)

    if page == "Today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        title = "📊 Today's Trading PnL Analysis"
        st.info("Fetching today's trades from Binance API...")
        trades = get_trades_since(int(start.timestamp() * 1000))
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        title = "📈 Month-to-Date Trading PnL Analysis"
        st.info("Loading trades from Excel file...")
        trades = get_trades_from_file(start)

    st.title(title)
    st.caption(f"Analysis period: {start.strftime('%Y-%m-%d %H:%M')} UTC to {now.strftime('%Y-%m-%d %H:%M')} UTC")

    if not trades:
        st.warning("⚠️ No trades found for the selected period.")
        return

    # Display basic info
    tokens = sorted({t["symbol"] for t in trades})
    st.subheader("📋 Trading Summary")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Tokens Traded", len(tokens))
    with col2:
        st.metric("Total Trades", len(trades))

    with st.expander("View Traded Tokens"):
        st.write(", ".join(tokens))

    # Calculate and display PnL
    pnl_df = calculate_token_pnl(trades)
    if pnl_df.empty:
        st.warning("⚠️ No PnL data to display.")
        return

    st.subheader("💰 PnL Analysis")

    # Style the dataframe
    styled = pnl_df.style.apply(highlight_total_and_negative, axis=1).format({
        "Realized PnL": "${:.2f}",
        "BNB Fees": "{:.5f}",
        "BNB Fees (USDC)": "${:.2f}",
        "Direct USDC Fees": "${:.2f}",
        "Total Fees (USDC)": "${:.2f}",
        "Net PnL": "${:.2f}",
    })

    st.dataframe(styled, use_container_width=True)

    # Display metrics
    total = pnl_df.iloc[-1]
    st.subheader("📊 Key Metrics")

    col1, col2, col3, col4 = st.columns(4)

    net_pnl = total["Net PnL"]
    pnl_color = "normal" if net_pnl >= 0 else "inverse"

    col1.metric(
        "Net PnL",
        f"${net_pnl:.2f}",
        delta=f"${net_pnl:.2f}",
        delta_color=pnl_color
    )

    col2.metric("Total Fees", f"${total['Total Fees (USDC)']:.2f}")
    col3.metric("Total Trades", f"{int(total['Trades'])}")

    avg_fee = total["Total Fees (USDC)"] / total["Trades"] if total["Trades"] else 0
    col4.metric("Avg Fee/Trade", f"${avg_fee:.2f}")

    # Visualization
    st.subheader("📈 PnL Visualization")
    chart = create_pnl_chart(pnl_df)
    if chart:
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("ℹ️ Not enough data to create a chart.")

    # Raw data section
    with st.expander("🔍 View Raw Trade Data"):
        df_trades = pd.DataFrame(trades)
        if not df_trades.empty:
            st.dataframe(df_trades, use_container_width=True)


if __name__ == "__main__":
    main()