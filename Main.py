import os
import time
import urllib.parse
import requests

from eth_account import Account
from eth_account.messages import encode_typed_data


# ============================================================
# ASTER FUTURES TESTNET V3
# ============================================================

BASE_URL = "https://fapi.asterdex-testnet.com"

API_WALLET = os.getenv("ASTER_API_WALLET", "").strip()
PRIVATE_KEY = os.getenv("ASTER_API_PRIVATE_KEY", "").strip()


# ============================================================
# EIP-712
# ============================================================

DOMAIN = {
    "name": "AsterSignTransaction",
    "version": "1",
    "chainId": 714,
    "verifyingContract": "0x0000000000000000000000000000000000000000",
}

TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "Message": [
        {"name": "msg", "type": "string"},
    ],
}


# ============================================================
# HTTP
# ============================================================

session = requests.Session()

session.headers.update({
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "PythonApp/1.0",
})


# ============================================================
# CREDENTIALS
# ============================================================

def validate_credentials():
    if not API_WALLET:
        raise RuntimeError("ASTER_API_WALLET is missing")

    if not PRIVATE_KEY:
        raise RuntimeError("ASTER_API_PRIVATE_KEY is missing")

    try:
        account = Account.from_key(PRIVATE_KEY)
    except Exception as e:
        raise RuntimeError(
            f"Invalid ASTER_API_PRIVATE_KEY: {e}"
        )

    derived = account.address

    if derived.lower() != API_WALLET.lower():
        raise RuntimeError(
            f"API private key mismatch: "
            f"derived={derived}, wallet={API_WALLET}"
        )

    print("Credential check: OK")
    print("Signer:", API_WALLET)


# ============================================================
# NONCE
# ============================================================

_last_second = 0
_nonce_counter = 0


def get_nonce():
    global _last_second
    global _nonce_counter

    now_second = int(time.time())

    if now_second == _last_second:
        _nonce_counter += 1
    else:
        _last_second = now_second
        _nonce_counter = 0

    return (
        now_second * 1_000_000
        + _nonce_counter
    )


# ============================================================
# SIGNATURE
# ============================================================

def sign_params(params):
    encoded = urllib.parse.urlencode(params)

    typed_data = {
        "types": TYPES,
        "primaryType": "Message",
        "domain": DOMAIN,
        "message": {
            "msg": encoded
        },
    }

    message = encode_typed_data(
        full_message=typed_data
    )

    signed = Account.sign_message(
        message,
        private_key=PRIVATE_KEY
    )

    return encoded, signed.signature.hex()


# ============================================================
# PUBLIC GET
# ============================================================

def public_get(path, params=None):
    response = session.get(
        BASE_URL + path,
        params=params,
        timeout=20
    )

    if not response.ok:
        print("ASTER PUBLIC ERROR:")
        print(response.text)

    response.raise_for_status()

    return response.json()


# ============================================================
# SIGNED GET
# ============================================================

def signed_get(path, params=None):
    if params is None:
        params = {}

    params = dict(params)

    # Required V3 authentication parameters
    params["nonce"] = get_nonce()
    params["signer"] = API_WALLET

    encoded, signature = sign_params(params)

    url = (
        BASE_URL
        + path
        + "?"
        + encoded
        + "&signature="
        + signature
    )

    print("SIGNED:", path)

    response = session.get(
        url,
        timeout=20
    )

    if not response.ok:
        print("ASTER ERROR:")
        print(response.text)

    response.raise_for_status()

    return response.json()


# ============================================================
# PING
# ============================================================

def ping():
    return public_get("/fapi/v3/ping")


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():
    return public_get("/fapi/v3/time")


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():
    return public_get("/fapi/v3/exchangeInfo")


# ============================================================
# BALANCE
# ============================================================

def get_balance():
    return signed_get(
        "/fapi/v3/balance",
        {
            "timestamp": int(time.time() * 1000)
        }
    )


# ============================================================
# POSITION
# ============================================================

def get_positions():
    return signed_get(
        "/fapi/v3/positionRisk",
        {
            "timestamp": int(time.time() * 1000)
        }
    )


# ============================================================
# KLINES
# ============================================================

def get_klines(
    symbol="BTCUSDT",
    interval="1m",
    limit=100
):
    return public_get(
        "/fapi/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


# ============================================================
# SIGNAL
# ============================================================

def calculate_signal(klines):

    if len(klines) < 20:
        return "WAIT"

    closes = [
        float(candle[4])
        for candle in klines
    ]

    fast_ma = sum(closes[-5:]) / 5
    slow_ma = sum(closes[-20:]) / 20

    if fast_ma > slow_ma:
        return "BUY"

    if fast_ma < slow_ma:
        return "SELL"

    return "WAIT"


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("ASTER FUTURES V3 TESTNET BOT")
    print("=" * 60)

    # 1. Credentials
    validate_credentials()

    # 2. Connectivity
    print("\nTesting connection...")

    print("PING:", ping())

    server = get_server_time()
    print("SERVER TIME:", server)

    # 3. Exchange info
    print("\nLoading exchange info...")

    exchange = get_exchange_info()

    symbols = {
        item["symbol"]
        for item in exchange.get("symbols", [])
    }

    if "BTCUSDT" not in symbols:
        raise RuntimeError(
            "BTCUSDT is not available on Futures Testnet"
        )

    print("BTCUSDT: OK")

    # 4. Account balance
    print("\nLoading balance...")

    balance = get_balance()

    print("BALANCE:")
    print(balance)

    # 5. Positions
    print("\nLoading positions...")

    positions = get_positions()

    print("POSITIONS:")
    print(positions)

    # 6. Trading loop
    print("\nBOT IS RUNNING")
    print("-" * 60)

    while True:

        try:

            klines = get_klines(
                symbol="BTCUSDT",
                interval="1m",
                limit=100
            )

            last_price = float(
                klines[-1][4]
            )

            signal = calculate_signal(
                klines
            )

            print(
                f"BTCUSDT | "
                f"Price: {last_price} | "
                f"Signal: {signal}"
            )

            time.sleep(30)

        except Exception as e:

            print("LOOP ERROR:", e)

            time.sleep(30)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
