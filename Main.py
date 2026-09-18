import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone


# ============================================================
# SETTINGS
# ============================================================

STARTING_BALANCE = 100.0
RISK_PER_TRADE = 0.10
MAX_LEVERAGE = 20
MAX_POSITIONS = 6

ASTER_BASE_URL = "https://fapi.asterdex.com"

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "LINKUSDT",
]

positions = {}
balance = STARTING_BALANCE


# ============================================================
# ASTER MARKET DATA
# ============================================================

def get_data(symbol, interval="1m", limit=100):

    url = (
        f"{ASTER_BASE_URL}/fapi/v1/klines"
        f"?symbol={symbol}"
        f"&interval={interval}"
        f"&limit={limit}"
    )

    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=15) as response:

            status = response.status
            body = response.read().decode("utf-8")

        if status != 200:
            raise RuntimeError(
                f"Aster HTTP {status}: {body[:500]}"
            )

        data = json.loads(body)

        if not isinstance(data, list):
            raise RuntimeError(
                f"Unexpected Aster response: {data}"
            )

        candles = []

        for x in data:

            if len(x) < 6:
                continue

            candles.append({
                "open": float(x[1]),
                "high": float(x[2]),
                "low": float(x[3]),
                "close": float(x[4]),
                "volume": float(x[5]),
            })

        if not candles:
            raise RuntimeError(
                f"No candle data returned for {symbol}"
            )

        return candles

    except urllib.error.HTTPError as error:

        body = error.read().decode(
            "utf-8",
            errors="replace"
        )

        print("")
        print("ASTER HTTP ERROR")
        print("Symbol:", symbol)
        print("HTTP:", error.code)
        print("Body:", body[:500])
        print("")

        raise

    except Exception as error:

        print(
            "ASTER DATA ERROR:",
            symbol,
            repr(error)
        )

        raise


# ============================================================
# ATR
# ============================================================

def atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    values = []

    for i in range(1, len(candles)):

        high = candles[i]["high"]
        low = candles[i]["low"]
        previous_close = candles[i - 1]["close"]

        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

        values.append(true_range)

    return sum(values[-period:]) / period


# ============================================================
# RSI
# ============================================================

def rsi(candles, period=14):

    if len(candles) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(candles)):

        change = (
            candles[i]["close"]
            - candles[i - 1]["close"]
        )

        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze(symbol):

    candles_1m = get_data(
        symbol,
        "1m",
        120
    )

    candles_5m = get_data(
        symbol,
        "5m",
        120
    )

    if len(candles_1m) < 100:
        return None

    if len(candles_5m) < 20:
        return None

    price = candles_1m[-1]["close"]

    highs = [
        x["high"]
        for x in candles_1m[-80:]
    ]

    lows = [
        x["low"]
        for x in candles_1m[-80:]
    ]

    range_high = max(highs)
    range_low = min(lows)

    range_width = (
        range_high - range_low
    )

    current_atr = atr(
        candles_1m,
        14
    )

    current_rsi = rsi(
        candles_1m,
        14
    )

    if current_atr is None:
        return None

    if current_rsi is None:
        return None

    if range_width <= current_atr * 2:
        return None

    volume_now = (
        candles_1m[-1]["volume"]
    )

    average_volume = (
        sum(
            x["volume"]
            for x in candles_1m[-20:]
        ) / 20
    )

    slow_price = (
        candles_5m[-1]["close"]
    )

    slow_average = (
        sum(
            x["close"]
            for x in candles_5m[-20:]
        ) / 20
    )

    score = 0
    side = None

    near_low = (
        price
        <= range_low + range_width * 0.20
    )

    near_high = (
        price
        >= range_high - range_width * 0.20
    )

    # ========================================================
    # LONG
    # ========================================================

    if near_low:

        if current_rsi < 45:
            score += 30

        if volume_now >= average_volume * 0.8:
            score += 20

        if slow_price >= slow_average * 0.995:
            score += 20

        if price > candles_1m[-2]["close"]:
            score += 20

        if score >= 60:
            side = "LONG"

    # ========================================================
    # SHORT
    # ========================================================

    elif near_high:

        if current_rsi > 55:
            score += 30

        if volume_now >= average_volume * 0.8:
            score += 20

        if slow_price <= slow_average * 1.005:
            score += 20

        if price < candles_1m[-2]["close"]:
            score += 20

        if score >= 60:
            side = "SHORT"

    if side is None:
        return None

    return {
        "symbol": symbol,
        "side": side,
        "price": price,
        "atr": current_atr,
        "score": score,
        "range_low": range_low,
        "range_high": range_high,
    }


# ============================================================
# OPEN PAPER POSITION
# ============================================================

def open_paper_position(signal):

    global balance

    symbol = signal["symbol"]

    if symbol in positions:
        return

    if len(positions) >= MAX_POSITIONS:
        return

    risk_money = (
        balance * RISK_PER_TRADE
    )

    price = signal["price"]

    current_atr = signal["atr"]

    stop_distance = max(
        current_atr * 1.5,
        price * 0.002,
    )

    leverage = int(
        min(
            MAX_LEVERAGE,
            max(
                1,
                1 / (
                    stop_distance / price
                ),
            ),
        )
    )

    quantity = (
        risk_money / stop_distance
    )

    if signal["side"] == "LONG":

        stop = (
            price - stop_distance
        )

        take_profit = (
            price
            + stop_distance * 2
        )

    else:

        stop = (
            price + stop_distance
        )

        take_profit = (
            price
            - stop_distance * 2
        )

    positions[symbol] = {

        "side": signal["side"],

        "entry": price,

        "quantity": quantity,

        "stop": stop,

        "take_profit": take_profit,

        "leverage": leverage,

        "score": signal["score"],

        "opened_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
    }

    print("")
    print("======================================")
    print("          PAPER ENTRY")
    print("======================================")
    print("Symbol:", symbol)
    print("Side:", signal["side"])
    print("Entry:", round(price, 6))
    print("Stop:", round(stop, 6))
    print(
        "Take Profit:",
        round(take_profit, 6)
    )
    print("Leverage:", leverage, "x")
    print(
        "Signal Score:",
        signal["score"]
    )
    print("======================================")
    print("")


# ============================================================
# MONITOR POSITIONS
# ============================================================

def monitor_positions():

    global balance

    for symbol in list(
        positions.keys()
    ):

        position = positions[symbol]

        try:

            candles = get_data(
                symbol,
                "1m",
                2
            )

            price = candles[-1]["close"]

            side = position["side"]

            entry = position["entry"]

            quantity = position["quantity"]

            exit_price = None
            reason = None

            # =================================================
            # LONG
            # =================================================

            if side == "LONG":

                if price <= position["stop"]:

                    exit_price = (
                        position["stop"]
                    )

                    reason = "STOP LOSS"

                elif price >= position["take_profit"]:

                    exit_price = (
                        position["take_profit"]
                    )

                    reason = "TAKE PROFIT"

            # =================================================
            # SHORT
            # =================================================

            else:

                if price >= position["stop"]:

                    exit_price = (
                        position["stop"]
                    )

                    reason = "STOP LOSS"

                elif price <= position["take_profit"]:

                    exit_price = (
                        position["take_profit"]
                    )

                    reason = "TAKE PROFIT"

            # =================================================
            # CLOSE POSITION
            # =================================================

            if exit_price is not None:

                if side == "LONG":

                    pnl = (
                        exit_price - entry
                    ) * quantity

                else:

                    pnl = (
                        entry - exit_price
                    ) * quantity

                balance += pnl

                print("")
                print("======================================")
                print("          PAPER EXIT")
                print("======================================")
                print("Symbol:", symbol)
                print("Reason:", reason)
                print(
                    "Exit:",
                    round(exit_price, 6)
                )
                print(
                    "PnL:",
                    round(pnl, 4),
                    "USDT"
                )
                print(
                    "Balance:",
                    round(balance, 4),
                    "USDT"
                )
                print("======================================")
                print("")

                del positions[symbol]

        except Exception as error:

            print(
                "Position monitor error:",
                symbol,
                repr(error)
            )


# ============================================================
# MAIN LOOP
# ============================================================

def main():

    print("")
    print("======================================")
    print("     ASTER FUTURES PAPER BOT")
    print("======================================")
    print(
        "Starting balance:",
        STARTING_BALANCE,
        "USDT"
    )
    print(
        "Risk per trade:",
        RISK_PER_TRADE * 100,
        "%"
    )
    print(
        "Maximum leverage:",
        MAX_LEVERAGE,
        "x"
    )
    print(
        "Maximum positions:",
        MAX_POSITIONS
    )
    print("Exchange: ASTER")
    print("Mode: PAPER TRADING")
    print("======================================")
    print("")

    while True:

        try:

            # -----------------------------------------------
            # Monitor existing positions
            # -----------------------------------------------

            monitor_positions()

            # -----------------------------------------------
            # Scan markets
            # -----------------------------------------------

            for symbol in SYMBOLS:

                if len(positions) >= MAX_POSITIONS:
                    break

                try:

                    signal = analyze(symbol)

                    if signal:

                        print(
                            datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            "| SIGNAL",
                            signal["symbol"],
                            signal["side"],
                            "| score:",
                            signal["score"],
                        )

                        open_paper_position(
                            signal
                        )

                except Exception as error:

                    print(
                        "Analysis error:",
                        symbol,
                        repr(error)
                    )

            # -----------------------------------------------
            # Status
            # -----------------------------------------------

            print(
                datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "| Exchange: ASTER",
                "| Balance:",
                round(balance, 4),
                "| Open positions:",
                len(positions),
            )

            # -----------------------------------------------
            # Wait one minute
            # -----------------------------------------------

            time.sleep(60)

        except Exception as error:

            print(
                "Main loop error:",
                repr(error)
            )

            time.sleep(30)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
