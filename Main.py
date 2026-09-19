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
USER_ADDRESS = os.getenv("ASTER_USER_ADDRESS", "").strip()


# ============================================================
# EIP-712
# ============================================================

DOMAIN = {
    "name": "AsterSignTransaction",
    "version": "1",
    "chainId": 1666,
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
        raise RuntimeError(
            "ASTER_API_WALLET is missing"
        )

    if not PRIVATE_KEY:
        raise RuntimeError(
            "ASTER_API_PRIVATE_KEY is missing"
        )

    if not USER_ADDRESS:
        raise RuntimeError(
            "ASTER_USER_ADDRESS is missing"
        )

    # Validate user address format
    if (
        not USER_ADDRESS.startswith("0x")
        or len(USER_ADDRESS) != 42
    ):
        raise RuntimeError(
            "ASTER_USER_ADDRESS must be a valid "
            "20-byte EVM address"
        )

    try:
        int(USER_ADDRESS[2:], 16)
    except ValueError:
        raise RuntimeError(
            "ASTER_USER_ADDRESS contains invalid hex characters"
        )

    try:
        account = Account.from_key(PRIVATE_KEY)

    except Exception as e:
        raise RuntimeError(
            f"Invalid ASTER_API_PRIVATE_KEY: {e}"
        )

    derived = account.address

    if derived.lower() != API_WALLET.lower():
        raise RuntimeError(
            "API private key mismatch: "
            f"derived={derived}, "
            f"wallet={API_WALLET}"
        )

    print("Credential check: OK")
    print("User:", USER_ADDRESS)
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
# PARAMETER STRING
# ============================================================

def build_param_string(params):

    # Aster V3:
    # - all values as strings
    # - ASCII-sort parameter names
    # - exact resulting string is signed

    normalized = {}

    for key, value in params.items():
        normalized[str(key)] = str(value)

    sorted_items = sorted(
        normalized.items(),
        key=lambda item: item[0]
    )

    return urllib.parse.urlencode(
        sorted_items
    )


# ============================================================
# EIP-712 SIGNATURE
# ============================================================

def sign_params(params):

    param_string = build_param_string(
        params
    )

    typed_data = {
        "types": TYPES,
        "primaryType": "Message",
        "domain": DOMAIN,
        "message": {
            "msg": param_string
        },
    }

    message = encode_typed_data(
        full_message=typed_data
    )

    signed = Account.sign_message(
        message,
        private_key=PRIVATE_KEY
    )

    # Official Aster format:
    # signed.signature.hex()
    signature = signed.signature.hex()

    return param_string, signature


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

    request_params = dict(params)

    # Official V3 authentication fields
    request_params["user"] = USER_ADDRESS
    request_params["signer"] = API_WALLET
    request_params["nonce"] = str(
        get_nonce()
    )

    # IMPORTANT:
    # The exact same sorted/encoded string
    # must be signed and sent before signature.
    param_string, signature = sign_params(
        request_params
    )

    url = (
        BASE_URL
        + path
        + "?"
        + param_string
        + "&signature="
        + signature
    )

    print("SIGNED:", path)
    print("MSG:", param_string)

    response = session.get(
        url,
        timeout=20
    )

    if not response.ok:

        print("ASTER ERROR:")
        print(response.text)

        print("URL:")
        print(url)

    response.raise_for_status()

    return response.json()


# ============================================================
# PING
# ============================================================

def ping():

    return public_get(
        "/fapi/v3/ping"
    )


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():

    return public_get(
        "/fapi/v3/time"
    )


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    return public_get(
        "/fapi/v3/exchangeInfo"
    )


# ============================================================
# BALANCE
# ============================================================

def get_balance():

    return signed_get(
        "/fapi/v3/balance"
    )


# ============================================================
# POSITIONS
# ============================================================

def get_positions():

    return signed_get(
        "/fapi/v3/positionRisk"
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

    validate_credentials()

    print("\nTesting connection...")

    print(
        "PING:",
        ping()
    )

    server = get_server_time()

    print(
        "SERVER TIME:",
        server
    )

    print(
        "\nLoading exchange info..."
    )

    exchange = get_exchange_info()

    symbols = {
        item["symbol"]
        for item in exchange.get(
            "symbols",
            []
        )
    }

    if "BTCUSDT" not in symbols:

        raise RuntimeError(
            "BTCUSDT is not available "
            "on Futures Testnet"
        )

    print("BTCUSDT: OK")

    print(
        "\nLoading balance..."
    )

    balance = get_balance()

    print("BALANCE:")
    print(balance)

    print(
        "\nLoading positions..."
    )

    positions = get_positions()

    print("POSITIONS:")
    print(positions)

    print(
        "\nBOT IS RUNNING"
    )

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

            print(
                "LOOP ERROR:",
                e
            )

            time.sleep(30)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
