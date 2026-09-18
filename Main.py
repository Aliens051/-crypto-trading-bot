import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_DOWN

from eth_account import Account
from eth_account.messages import encode_typed_data


# ============================================================
# ASTER FUTURES V3 — TESTNET ONLY
# ============================================================

ASTER_BASE_URL = "https://fapi.asterdex-testnet.com"
CHAIN_ID = 714
VERIFYING_CONTRACT = "0x0000000000000000000000000000000000000000"

ASTER_USER_ADDRESS = os.getenv("ASTER_USER_ADDRESS", "").strip()
ASTER_API_WALLET = os.getenv("ASTER_API_WALLET", "").strip()
ASTER_API_PRIVATE_KEY = os.getenv("ASTER_API_PRIVATE_KEY", "").strip()

STARTING_BALANCE = 100.0
RISK_PER_TRADE = 0.10
MAX_LEVERAGE = 20
MAX_POSITIONS = 6

SCAN_INTERVAL_SECONDS = 60
KLINE_LIMIT = 120

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

# Strategy parameters kept from the existing bot.
TAKE_PROFIT_PCT = 0.015
STOP_LOSS_PCT = 0.008

NONCE_LOCK = threading.Lock()
LAST_NONCE = 0


# ============================================================
# BASIC HTTP
# ============================================================

def http_json(url, method="GET", data=None, timeout=20):
    headers = {
        "User-Agent": "AsterDemoTradingBot/1.0",
        "Accept": "application/json",
    }

    body = None
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urllib.parse.urlencode(data).encode()

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"code": exc.code, "msg": raw}
        raise RuntimeError(f"Aster HTTP {exc.code}: {payload}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc}") from exc


def public_get(path, params=None):
    url = ASTER_BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return http_json(url, "GET")


# ============================================================
# V3 AUTHENTICATION
# ============================================================

def next_nonce():
    global LAST_NONCE

    with NONCE_LOCK:
        now = time.time_ns() // 1000
        if now <= LAST_NONCE:
            now = LAST_NONCE + 1
        LAST_NONCE = now
        return now


def validate_credentials():
    if not ASTER_USER_ADDRESS:
        raise RuntimeError("ASTER_USER_ADDRESS is missing")

    if not ASTER_API_WALLET:
        raise RuntimeError("ASTER_API_WALLET is missing")

    if not ASTER_API_PRIVATE_KEY:
        raise RuntimeError("ASTER_API_PRIVATE_KEY is missing")

    try:
        derived = Account.from_key(ASTER_API_PRIVATE_KEY).address
    except Exception as exc:
        raise RuntimeError("ASTER_API_PRIVATE_KEY is invalid") from exc

    if derived.lower() != ASTER_API_WALLET.lower():
        raise RuntimeError(
            "ASTER_API_PRIVATE_KEY does not belong to ASTER_API_WALLET"
        )

    print(f"Main account: {ASTER_USER_ADDRESS}")
    print(f"API signer:   {derived}")
    print("Aster mode:   FUTURES V3 TESTNET")


def sign_params(params):
    encoded = urllib.parse.urlencode(params)

    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Message": [
                {"name": "msg", "type": "string"},
            ],
        },
        "primaryType": "Message",
        "domain": {
            "name": "AsterSignTransaction",
            "version": "1",
            "chainId": CHAIN_ID,
            "verifyingContract": VERIFYING_CONTRACT,
        },
        "message": {
            "msg": encoded,
        },
    }

    message = encode_typed_data(full_message=typed_data)
    signed = Account.sign_message(
        message,
        private_key=ASTER_API_PRIVATE_KEY,
    )

    return signed.signature.hex()


def signed_request(path, method="GET", params=None):
    params = dict(params or {})

    params["signer"] = ASTER_API_WALLET
    params["nonce"] = str(next_nonce())

    signature = sign_params(params)
    params["signature"] = signature

    url = ASTER_BASE_URL + path

    if method == "GET":
        url += "?" + urllib.parse.urlencode(params)
        return http_json(url, "GET")

    return http_json(url, method, params)


# ============================================================
# MARKET DATA
# ============================================================

def get_data(symbol, interval="5m", limit=KLINE_LIMIT):
    data = public_get(
        "/fapi/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
    )

    return [
        {
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in data
    ]


def exchange_info():
    return public_get("/fapi/v3/exchangeInfo")


EXCHANGE_INFO = None
SYMBOL_RULES = {}


def load_symbol_rules():
    global EXCHANGE_INFO, SYMBOL_RULES

    EXCHANGE_INFO = exchange_info()

    for item in EXCHANGE_INFO.get("symbols", []):
        symbol = item.get("symbol")
        if not symbol:
            continue

        rules = {}

        for f in item.get("filters", []):
            ftype = f.get("filterType")
            rules[ftype] = f

        SYMBOL_RULES[symbol] = rules


def floor_step(value, step):
    value = Decimal(str(value))
    step = Decimal(str(step))

    if step <= 0:
        return float(value)

    units = (value / step).to_integral_value(rounding=ROUND_DOWN)
    result = units * step

    return float(result)


def quantity_for(symbol, price, balance):
    rules = SYMBOL_RULES.get(symbol, {})

    lot = rules.get("MARKET_LOT_SIZE") or rules.get("LOT_SIZE") or {}

    step = float(lot.get("stepSize", "0.001"))
    minimum = float(lot.get("minQty", "0.001"))
    maximum = float(lot.get("maxQty", "999999999"))

    # Same risk model as the original bot:
    # 10% account risk allocation, multiplied by leverage.
    notional = balance * RISK_PER_TRADE * MAX_LEVERAGE

    quantity = notional / price
    quantity = floor_step(quantity, step)

    if quantity < minimum:
        return 0.0

    return min(quantity, maximum)


# ============================================================
# INDICATORS / STRATEGY
# ============================================================

def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"]),
        )

        trs.append(tr)

    return sum(trs[-period:]) / period


def analyze(symbol):
    candles = get_data(symbol, "5m", KLINE_LIMIT)

    if len(candles) < 30:
        return None

    closes = [x["close"] for x in candles]
    volumes = [x["volume"] for x in candles]

    price = closes[-1]
    current_rsi = rsi(closes, 14)
    current_atr = atr(candles, 14)

    fast_ma = sma(closes, 9)
    slow_ma = sma(closes, 21)

    avg_volume = sma(volumes, 20)

    if (
        current_rsi is None
        or current_atr is None
        or fast_ma is None
        or slow_ma is None
        or avg_volume is None
    ):
        return None

    score_long = 0
    score_short = 0

    if fast_ma > slow_ma:
        score_long += 25
    elif fast_ma < slow_ma:
        score_short += 25

    if current_rsi < 35:
        score_long += 25
    elif current_rsi > 65:
        score_short += 25

    recent_high = max(x["high"] for x in candles[-20:-1])
    recent_low = min(x["low"] for x in candles[-20:-1])

    if price > recent_high:
        score_long += 25
    elif price < recent_low:
        score_short += 25

    if volumes[-1] > avg_volume * 1.15:
        if price > closes[-2]:
            score_long += 20
        elif price < closes[-2]:
            score_short += 20

    if current_atr > price * 0.002:
        if price > fast_ma:
            score_long += 15
        elif price < fast_ma:
            score_short += 15

    if score_long >= score_short and score_long >= 60:
        side = "LONG"
        score = score_long
    elif score_short > score_long and score_short >= 60:
        side = "SHORT"
        score = score_short
    else:
        side = None
        score = max(score_long, score_short)

    return {
        "symbol": symbol,
        "side": side,
        "score": score,
        "price": price,
        "rsi": current_rsi,
        "atr": current_atr,
    }


# ============================================================
# ACCOUNT / POSITIONS
# ============================================================

def get_balance():
    data = signed_request("/fapi/v3/balance", "GET", {})
    for item in data:
        if item.get("asset") == "USDT":
            return float(item.get("availableBalance", item.get("balance", 0)))
    return 0.0


def get_positions():
    data = signed_request("/fapi/v3/positionRisk", "GET", {})
    result = {}

    for p in data:
        amount = float(p.get("positionAmt", 0))

        if abs(amount) <= 0:
            continue

        result[p["symbol"]] = {
            "amount": amount,
            "entry_price": float(p.get("entryPrice", 0)),
            "position_side": p.get("positionSide", "BOTH"),
        }

    return result


def set_leverage(symbol):
    return signed_request(
        "/fapi/v3/leverage",
        "POST",
        {
            "symbol": symbol,
            "leverage": str(MAX_LEVERAGE),
        },
    )


# ============================================================
# REAL TESTNET ORDERS
# ============================================================

def market_order(symbol, side, quantity, reduce_only=False):
    params = {
        "symbol": symbol,
        "type": "MARKET",
        "side": side,
        "quantity": format(quantity, ".12f").rstrip("0").rstrip("."),
        "newOrderRespType": "RESULT",
    }

    if reduce_only:
        params["reduceOnly"] = "true"

    return signed_request(
        "/fapi/v3/order",
        "POST",
        params,
    )


def open_position(symbol, direction, price, balance):
    quantity = quantity_for(symbol, price, balance)

    if quantity <= 0:
        print(f"SKIP {symbol}: quantity below exchange minimum")
        return None

    set_leverage(symbol)

    order_side = "BUY" if direction == "LONG" else "SELL"

    result = market_order(
        symbol,
        order_side,
        quantity,
        reduce_only=False,
    )

    print(
        f"TESTNET ENTRY | {symbol} | {direction} | "
        f"qty={quantity} | response={result}"
    )

    return result


def close_position(symbol, position):
    amount = abs(float(position["amount"]))

    if amount <= 0:
        return None

    close_side = "SELL" if position["amount"] > 0 else "BUY"

    result = market_order(
        symbol,
        close_side,
        amount,
        reduce_only=True,
    )

    print(
        f"TESTNET EXIT | {symbol} | "
        f"side={close_side} | qty={amount} | response={result}"
    )

    return result


# ============================================================
# POSITION MANAGEMENT
# ============================================================

def manage_positions(positions):
    for symbol, position in list(positions.items()):
        candles = get_data(symbol, "5m", 2)

        if not candles:
            continue

        price = candles[-1]["close"]
        entry = position["entry_price"]

        if entry <= 0:
            continue

        amount = position["amount"]

        if amount > 0:
            pnl_pct = (price - entry) / entry

            if pnl_pct >= TAKE_PROFIT_PCT or pnl_pct <= -STOP_LOSS_PCT:
                close_position(symbol, position)

        elif amount < 0:
            pnl_pct = (entry - price) / entry

            if pnl_pct >= TAKE_PROFIT_PCT or pnl_pct <= -STOP_LOSS_PCT:
                close_position(symbol, position)


# ============================================================
# MAIN LOOP
# ============================================================

def main():
    print("==============================================")
    print("ASTER FUTURES V3 TESTNET TRADING BOT")
    print("==============================================")

    validate_credentials()

    print("Loading exchange information...")
    load_symbol_rules()

    print("Checking testnet account...")
    balance = get_balance()
    print(f"Testnet USDT balance: {balance}")

    while True:
        try:
            positions = get_positions()

            manage_positions(positions)

            positions = get_positions()
            balance = get_balance()

            print(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} | "
                f"ASTER TESTNET | Balance: {balance:.4f} | "
                f"Open positions: {len(positions)}"
            )

            if len(positions) < MAX_POSITIONS:
                for symbol in SYMBOLS:
                    if symbol in positions:
                        continue

                    try:
                        signal = analyze(symbol)

                        if not signal:
                            continue

                        if signal["side"]:
                            print(
                                f"SIGNAL {symbol} {signal['side']} | "
                                f"score: {signal['score']} | "
                                f"price: {signal['price']}"
                            )

                            open_position(
                                symbol,
                                signal["side"],
                                signal["price"],
                                balance,
                            )

                            positions = get_positions()

                            if len(positions) >= MAX_POSITIONS:
                                break

                    except Exception as exc:
                        print(f"ERROR {symbol}: {exc}")

            time.sleep(SCAN_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("Bot stopped.")
            break

        except Exception as exc:
            print(f"MAIN ERROR: {exc}")
            
            time.sleep(15)


if __name__ == "__main__":
    main()
 
