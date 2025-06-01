from credentials import API_KEY, API_SECRET
from binance.um_futures import UMFutures
from datetime import datetime, timezone
from binance.error import ClientError
import streamlit as st
import altair as alt
import pandas as pd
import warnings
import os

# suppress openpyxl “no default style” warning
warnings.filterwarnings("ignore", "Workbook contains no default style", UserWarning)

# Initialize Binance Futures client
client = UMFutures(API_KEY, API_SECRET)


def get_all_symbols() -> list[str]:
    info = client.exchange_info()
    return [s["symbol"]
            for s in info["symbols"]
            if s.get("contractType") == "PERPETUAL" and s["symbol"].endswith("USDC")]


def get_trades_since(start_time_ms: int) -> list[dict]:
    trades: list[dict] = []
    for symbol in get_all_symbols():
        try:
            trades.extend(
                client.get_account_trades(symbol=symbol,
                                          startTime=start_time_ms,
                                          recvWindow=6000))
        except ClientError as error:
            st.warning(f"Failed to fetch trades for {symbol}: {error}")
    return trades


def get_trades_from_file(start_datetime: datetime) -> list[dict]:
    if start_datetime.tzinfo is not None:
        start_datetime = start_datetime.astimezone(timezone.utc).replace(tzinfo=None)

    path = os.path.expanduser("~/Downloads/Export Trade History.xlsx")
    df = pd.read_excel(path, parse_dates=["Date(UTC)"])

    # Normalize numeric columns (strip leading ' if present)
    num_cols = ["Price", "Quantity", "Amount", "Fee", "Realized Profit"]
    for col in num_cols:
        df[col] = (df[col]
                   .astype(str)
                   .str.lstrip("'")
                   .replace("", "0")
                   .pipe(pd.to_numeric, errors="coerce"))

    df = df[df["Date(UTC)"] >= start_datetime]

    trades: list[dict] = []
    for _, row in df.iterrows():
        trades.append({"symbol": row["Symbol"],
                       "realizedPnl": float(row["Realized Profit"] or 0),
                       "commission": float(row["Fee"] or 0),
                       "commissionAsset": row["Fee Coin"]})
    return trades


def get_price(symbol: str) -> float:
    try:
        ticker = client.ticker_price(symbol=symbol)
        return float(ticker["price"])
    except ClientError as error:
        st.warning(f"Failed to get price for {symbol}: {error}")
        return 0.0


def calculate_token_pnl(trades: list[dict]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()

    bnb_price = get_price("BNBUSDC")
    data: dict[str, dict] = {}

    for trade in trades:
        sym = trade["symbol"]
        realized = float(trade["realizedPnl"])
        commission = float(trade["commission"])
        asset = trade["commissionAsset"]

        if sym not in data:
            data[sym] = {"realized_pnl": 0.0,
                         "bnb_fees": 0.0,
                         "usdc_fees": 0.0,
                         "trades": 0}

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
        rows.append({"Token": sym,
                     "Realized PnL": round(vals["realized_pnl"], 2),
                     "BNB Fees": round(vals["bnb_fees"], 5),
                     "BNB Fees (USDC)": round(bnb_fees_usdc, 2),
                     "Direct USDC Fees": round(vals["usdc_fees"], 2),
                     "Total Fees (USDC)": round(total_fees, 2),
                     "Net PnL": round(net_pnl, 2),
                     "Trades": vals["trades"]})

    df = pd.DataFrame(rows)
    if not df.empty:
        total = {"Token": "TOTAL",
                 "Realized PnL": df["Realized PnL"].sum(),
                 "BNB Fees": df["BNB Fees"].sum(),
                 "BNB Fees (USDC)": df["BNB Fees (USDC)"].sum(),
                 "Direct USDC Fees": df["Direct USDC Fees"].sum(),
                 "Total Fees (USDC)": df["Total Fees (USDC)"].sum(),
                 "Net PnL": df["Net PnL"].sum(),
                 "Trades": df["Trades"].sum()}
        df = pd.concat([df, pd.DataFrame([total])], ignore_index=True)

    return df


def create_pnl_chart(df: pd.DataFrame):
    df_chart = df[df["Token"] != "TOTAL"]
    if df_chart.empty:
        return None

    return (
        alt.Chart(df_chart)
        .mark_bar()
        .encode(
            x=alt.X("Token:N", sort="-y"),
            y=alt.Y("Net PnL:Q"),
            color=alt.condition(alt.datum["Net PnL"] > 0, alt.value("green"), alt.value("red")),
            tooltip=["Token", "Net PnL", "Realized PnL", "Total Fees (USDC)", "Trades"])
        .properties(title="PnL by Token", width=600)
    )


def highlight_total(row):
    """Bold the TOTAL row font only."""
    if row["Token"] == "TOTAL":
        return ["font-weight: bold"] * len(row)
    return [""] * len(row)


def main():
    st.set_page_config(page_title="Trading PnL Analysis", layout="wide")
    page = st.sidebar.radio("Select Period", ["Today", "Month-to-Date"])

    now = datetime.now(timezone.utc)
    if page == "Today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        title = "Today's Trading PnL Analysis"
        trades = get_trades_since(int(start.timestamp() * 1000))
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        title = "Month-to-Date Trading PnL Analysis"
        trades = get_trades_from_file(start)

    st.title(title)
    if st.button("Refresh Data"):
        st.rerun()

    if not trades:
        st.warning("No trades found for the selected period.")
        return

    tokens = sorted({t["symbol"] for t in trades})
    st.subheader("Traded Tokens")
    st.write(f"Number of tokens traded: {len(tokens)}")
    st.write(", ".join(tokens))

    pnl_df = calculate_token_pnl(trades)
    if pnl_df.empty:
        st.warning("No PnL data to display.")
        return

    st.subheader("PnL Analysis")
    styled = pnl_df.style.apply(highlight_total, axis=1).format(
        {
            "Realized PnL": "${:.2f}",
            "BNB Fees": "{:.5f}",
            "BNB Fees (USDC)": "${:.2f}",
            "Direct USDC Fees": "${:.2f}",
            "Total Fees (USDC)": "${:.2f}",
            "Net PnL": "${:.2f}",
        }
    )
    st.dataframe(styled, use_container_width=True)

    total = pnl_df.iloc[-1]
    col1, col2, col3, col4 = st.columns(4)
    pct = (total["Net PnL"] / abs(total["Realized PnL"]) * 100) if total["Realized PnL"] else 0
    col1.metric("Total PnL", f"${total['Net PnL']:.2f}", delta=f"{pct:.1f}%")
    col2.metric("Total Fees", f"${total['Total Fees (USDC)']:.2f}")
    col3.metric("Total Trades", f"{int(total['Trades'])}")
    avg_fee = total["Total Fees (USDC)"] / total["Trades"] if total["Trades"] else 0
    col4.metric("Fee/Trade Avg", f"${avg_fee:.2f}")

    st.subheader("PnL Visualization")
    chart = create_pnl_chart(pnl_df)
    if chart:
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("Not enough data to create a chart.")

    with st.expander("View Raw Trade Data"):
        df_trades = pd.DataFrame(trades)
        st.dataframe(df_trades, use_container_width=True)


if __name__ == "__main__":
    main()
