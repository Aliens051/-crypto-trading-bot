import os
import time
import urllib.parse
import requests

from eth_account import Account
from eth_account.messages import encode_structured_data


BASE_URL = "https://fapi.asterdex-testnet.com"

USER = os.environ["ASTER_USER_ADDRESS"].strip()
API_WALLET = os.environ["ASTER_API_WALLET"].strip()
PRIVATE_KEY = os.environ["ASTER_API_PRIVATE_KEY"].strip()

signer = Account.from_key(PRIVATE_KEY).address

print("==============================================")
print("ASTER FUTURES V3 TESTNET")
print("==============================================")
print("USER:", USER)
print("API WALLET:", API_WALLET)
print("DERIVED SIGNER:", signer)

if signer.lower() != API_WALLET.lower():
    raise RuntimeError(
        f"API private key mismatch: derived={signer}, wallet={API_WALLET}"
    )


session = requests.Session()

session.headers.update({
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "PythonApp/1.0",
})


TYPED_DATA = {
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
        "chainId": 714,
        "verifyingContract": "0x0000000000000000000000000000000000000000",
    },
    "message": {
        "msg": "",
    },
}


_last_second = 0
_nonce_counter = 0


def get_nonce():
    global _last_second
    global _nonce_counter

    now = int(time.time())

    if now == _last_second:
        _nonce_counter += 1
    else:
        _last_second = now
        _nonce_counter = 0

    return now * 1_000_000 + _nonce_counter


def sign_params(params):
    params = dict(params)

    params["nonce"] = str(get_nonce())
    params["signer"] = API_WALLET

    encoded = urllib.parse.urlencode(params)

    TYPED_DATA["message"]["msg"] = encoded

    message = encode_structured_data(TYPED_DATA)

    signed = Account.sign_message(
        message,
        private_key=PRIVATE_KEY,
    )

    params["signature"] = signed.signature.hex()

    return params


def public_get(path, params=None):
    response = session.get(
        BASE_URL + path,
        params=params or {},
        timeout=20,
    )

    print("PUBLIC:", path, response.status_code)
    print(response.text)

    response.raise_for_status()

    return response.json()


def signed_get(path, params=None):
    signed = sign_params(params or {})

    response = session.get(
        BASE_URL + path,
        params=signed,
        timeout=20,
    )

    print("SIGNED:", path, response.status_code)
    print(response.text)

    response.raise_for_status()

    return response.json()


def test_connection():
    public_get("/fapi/v3/ping")
    print("ASTER CONNECTION OK")


def get_time():
    return public_get("/fapi/v3/time")


def get_exchange_info():
    return public_get("/fapi/v3/exchangeInfo")


def get_balance():
    return signed_get("/fapi/v3/balance")


def get_positions():
    return signed_get("/fapi/v3/positionRisk")


def get_klines(symbol="BTCUSDT", interval="5m", limit=100):
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

    print("SERVER TIME:")
    get_time()

    print("EXCHANGE INFO:")
    get_exchange_info()

    print("BALANCE:")
    get_balance()

    print("POSITIONS:")
    get_positions()

    print("BTCUSDT KLINES:")
    get_klines()

    print("==============================================")
    print("ASTER FUTURES V3 TESTNET AUTH OK")
    print("==============================================")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
 
