import os
import time
import urllib.parse
import requests
from eth_account import Account
from eth_account.messages import encode_typed_data

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


def nonce():
    return int(time.time() * 1_000_000)


def sign_params(params):
    params = dict(params)

    params["nonce"] = str(nonce())
    params["signer"] = API_WALLET

    query = urllib.parse.urlencode(params)

    typed_data = {
        "types": TYPES,
        "primaryType": "Message",
        "domain": DOMAIN,
        "message": {
            "msg": query,
        },
    }

    encoded = encode_typed_data(full_message=typed_data)

    signed = Account.sign_message(
        encoded,
        private_key=PRIVATE_KEY,
    )

    params["signature"] = signed.signature.hex()

    return params


def public_get(path, params=None):
    r = session.get(
        BASE_URL + path,
        params=params or {},
        timeout=20,
    )

    print("PUBLIC", path, r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def signed_get(path, params=None):
    signed = sign_params(params or {})

    r = session.get(
        BASE_URL + path,
        params=signed,
        timeout=20,
    )

    print("SIGNED", path, r.status_code, r.text)

    r.raise_for_status()
    return r.json()


def test_connection():
    public_get("/fapi/v3/ping")


def get_server_time():
    return public_get("/fapi/v3/time")


def get_exchange_info():
    return public_get("/fapi/v3/exchangeInfo")


def get_balance():
    return signed_get(
        "/fapi/v3/balance",
        {}
    )


def get_positions():
    return signed_get(
        "/fapi/v3/positionRisk",
        {}
    )


def get_klines():
    return public_get(
        "/fapi/v3/klines",
        {
            "symbol": "BTCUSDT",
            "interval": "5m",
            "limit": 100,
        },
    )


def main():
    print("TEST CONNECTION")
    test_connection()

    print("SERVER TIME")
    get_server_time()

    print("EXCHANGE INFO")
    get_exchange_info()

    print("BALANCE")
    get_balance()

    print("POSITIONS")
    get_positions()

    print("KLINES")
    get_klines()

    print("==============================================")
    print("ASTER V3 TESTNET AUTH CHECK PASSED")
    print("==============================================")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
