
import time
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


# ---------- INIT: trading + data clients ----------

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
market_data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# ---------- Account health check (your existing part) ----------

url = "https://paper-api.alpaca.markets/v2/account"
headers = {
    "accept": "application/json",
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": SECRET_KEY,
}
response = requests.get(url, headers=headers)
print(response.text)

# ---------- Test order: buy 1 share of AAPL (your existing part) ----------

test_order = MarketOrderRequest(
    symbol="AAPL",
    qty=1,
    side=OrderSide.BUY,
    time_in_force=TimeInForce.DAY,
)
test_result = trading_client.submit_order(order_data=test_order)
print("Test AAPL order:", test_result)

# ---------- Pairs trading setup: GOOGL vs MSFT ----------

stock1 = "GOOGL"
stock2 = "MSFT"
days = 100

now = datetime.now(tz=timezone.utc)
start = now - timedelta(days=days)

# IMPORTANT: no `end` parameter – lets Alpaca default it to
# “now - 15 minutes” on free plans to avoid recent SIP restriction. [[Historical default end](https://forum.alpaca.markets/t/15092)]
request_1 = StockBarsRequest(
    symbol_or_symbols=stock1,
    start=start,
    timeframe=TimeFrame.Day,
    limit=days,
)

request_2 = StockBarsRequest(
    symbol_or_symbols=stock2,
    start=start,
    timeframe=TimeFrame.Day,
    limit=days,
)

while True:
    # 1) Pull historical daily bars for both symbols
    stock1_bars = market_data_client.get_stock_bars(request_1)
    stock2_bars = market_data_client.get_stock_bars(request_2)

    # Extract close prices
    data_1 = [bar.close for bar in stock1_bars.data[stock1]]
    data_2 = [bar.close for bar in stock2_bars.data[stock2]]

    # Sanity check: need at least 2 bars to compute today vs yesterday
    if len(data_1) < 2 or len(data_2) < 2:
        print("Not enough data yet, sleeping 60s...")
        time.sleep(60)
        continue

    # 2) Create DataFrame and compute spread (similar to examples) [[Algo bot pairs logic](https://alpaca.markets/learn/algorithmic-trading-bot-7-steps#step-5-build-a-trading-strategy-into-the-script-and-add-certain-messages-to-email); [Pairs spread calc](https://alpaca.markets/learn/pairs-trading#example5)]
    hist_close = pd.DataFrame(data_1, columns=[stock1])
    hist_close[stock2] = data_2

    spread_df = hist_close.pct_change()
    spread_df["spread"] = spread_df[stock1] - spread_df[stock2]

    # 3) Threshold = max absolute divergence over last 20 days [[Pairs spread calc](https://alpaca.markets/learn/pairs-trading#example5)]
    max_divergence = spread_df["spread"].tail(20).abs().max()

    # 4) Current 1‑day relative performance difference
    curr_1 = data_1[-1]
    prev_1 = data_1[-2]
    curr_2 = data_2[-1]
    prev_2 = data_2[-2]

    # Rough 1‑day % move for each, then difference
    pchg_1 = (curr_1 / prev_1) - 1
    pchg_2 = (curr_2 / prev_2) - 1
    curr_spread = pchg_1 - pchg_2

    print(f"Current spread: {curr_spread:.6f}, max divergence: {max_divergence:.6f}")

    # 5) If divergence exceeds threshold, enter pairs trade
    if abs(curr_spread) > max_divergence:
        acct = trading_client.get_account()
        acct_size = float(acct.equity)

        # Simple sizing: use full equity per leg (you may want something smaller)
        qty1 = round(acct_size / curr_1)
        qty2 = round(acct_size / curr_2)

        # Decide which stock is "down" vs "up"
        # spread = GOOGL - MSFT
        # spread < 0 -> GOOGL underperformed (down), MSFT outperformed (up)
        if curr_spread < 0:
            side1 = OrderSide.BUY   # GOOGL (down) -> buy
            side2 = OrderSide.SELL  # MSFT (up)   -> short
        else:
            side1 = OrderSide.SELL  # GOOGL (up)   -> short
            side2 = OrderSide.BUY   # MSFT (down)  -> buy

        print(f"Entering pairs trade: {side1} {qty1} {stock1}, {side2} {qty2} {stock2}")

        trading_client.submit_order(
            MarketOrderRequest(
                symbol=stock1,
                qty=qty1,
                side=side1,
                time_in_force=TimeInForce.DAY,
            )
        )
        trading_client.submit_order(
            MarketOrderRequest(
                symbol=stock2,
                qty=qty2,
                side=side2,
                time_in_force=TimeInForce.DAY,
            )
        )

        break  # exit loop after first trade; remove if you want it to keep running

    # 6) Sleep before re-checking (e.g., once per minute)
    time.sleep(60)