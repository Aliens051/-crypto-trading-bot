import os
import time
import hmac
import hashlib
import requests
from eth_account import Account
from eth_account.messages import encode_defunct

BASE_URL = "https://fapi.asterdex.com"

USER = os.environ["ASTER_USER_ADDRESS"].strip()
API_WALLET = os.environ["ASTER_API_WALLET"].strip()
PRIVATE_KEY = os.environ["ASTER_API_PRIVATE_KEY"].strip()

# Validate signer
signer = Account.from_key(PRIVATE_KEY).address

print("==============================================")
print("ASTER FUTURES V3")
print("==============================================")
print("USER:", USER)
print("API WALLET:", API_WALLET)
print("DERIVED SIGNER:", signer)

if signer.lower() != API_WALLET.lower():
    raise RuntimeError(
        f"API private key mismatch: derived={signer}, wallet={API_WALLET}"
    )

session = requests.Session()
session.headers.update({"Content-Type": "application/x-www-form-urlencoded"})


def server_time():
    r = session.get(f"{BASE_URL}/fapi/v3/time", timeout=15)
    r.raise_for_status()
    return r.json()["serverTime"]


def sign_params(params):
    query = "&".join(
        f"{k}={v}" for k, v in params.items()
    )

    message = encode_defunct(text=query)
    signed = Account.sign_message(message, PRIVATE_KEY)

    params["signature"] = signed.signature.hex()
    return params


def signed_get(path, params=None):
    params = params or {}

    params["timestamp"] = server_time()

    params = sign_params(params)

    r = session.get(
        f"{BASE_URL}{path}",
        params=params,
        timeout=20,
    )

    print("GET", path, r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def signed_post(path, params=None):
    params = params or {}

    params["timestamp"] = server_time()

    params = sign_params(params)

    r = session.post(
        f"{BASE_URL}{path}",
        data=params,
        timeout=20,
    )

    print("POST", path, r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def public_get(path, params=None):
    r = session.get(
        f"{BASE_URL}{path}",
        params=params or {},
        timeout=20,
    )

    print("PUBLIC", path, r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def test_connection():
    public_get("/fapi/v3/ping")
    print("ASTER CONNECTION: OK")


def get_exchange_info():
    return public_get("/fapi/v3/exchangeInfo")


def get_balance():
    return signed_get("/fapi/v3/balance")


def get_positions():
    return signed_get("/fapi/v3/positionRisk")


def get_klines(symbol, interval="5m", limit=100):
    return public_get(
        "/fapi/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
    )


def main():
    test_connection()

    print("EXCHANGE INFO:")
    get_exchange_info()

    print("BALANCE:")
    get_balance()

    print("POSITIONS:")
    get_positions()

    print("BTCUSDT KLINES:")
    get_klines("BTCUSDT")

    print("==============================================")
    print("BOT RUNNING")
    print("==============================================")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
 
