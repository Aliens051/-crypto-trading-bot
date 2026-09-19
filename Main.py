import os
import time
import urllib.parse
import requests

from eth_account import Account
from eth_account.messages import encode_typed_data


# ============================================================
# Aster Futures V3 TESTNET - AGENT DIAGNOSTIC ONLY
# This file does NOT place orders.
# ============================================================

BASE_URL = "https://fapi.asterdex-testnet.com"

API_WALLET = os.getenv("ASTER_API_WALLET", "").strip()
PRIVATE_KEY = os.getenv("ASTER_API_PRIVATE_KEY", "").strip()
USER_ADDRESS = os.getenv("ASTER_USER_ADDRESS", "").strip()

# Official Aster Futures Testnet EIP-712 chain ID
CHAIN_ID = 714

NONCE_COUNTER = 0


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def fail(message):
    print("\nERROR:")
    print(message)
    raise SystemExit(1)


def normalize_address(address):
    return address.lower()


def validate_address(name, address):
    if not address:
        fail(f"{name} is missing.")

    if not address.startswith("0x") or len(address) != 42:
        fail(
            f"{name} is not a valid EVM address.\n"
            f"Length received: {len(address)}"
        )


def get_server_time_ms():
    url = f"{BASE_URL}/fapi/v3/time"

    response = requests.get(url, timeout=15)

    print("\nSERVER TIME HTTP:", response.status_code)

    response.raise_for_status()

    data = response.json()

    if "serverTime" not in data:
        fail(f"Unexpected server time response:\n{data}")

    return int(data["serverTime"])


def get_nonce(server_time_ms):
    global NONCE_COUNTER

    NONCE_COUNTER += 1

    # Server time is milliseconds.
    # Aster expects a microseconds-style nonce.
    return (int(server_time_ms) * 1000) + NONCE_COUNTER


def canonical_query(params):
    """
    Create the exact query string that will also be signed.
    """
    items = sorted(
        [(str(k), str(v)) for k, v in params.items()],
        key=lambda x: x[0]
    )

    return urllib.parse.urlencode(
        items,
        doseq=False,
        safe=""
    )


def sign_message(query_string):
    """
    Official trading/authentication mode:
    EIP-712 fixed Message type, signing only msg.
    """

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
            "verifyingContract": "0x0000000000000000000000000000000000000000",
        },
        "message": {
            "msg": query_string,
        },
    }

    signable = encode_typed_data(full_message=typed_data)

    signed = Account.sign_message(
        signable,
        private_key=PRIVATE_KEY
    )

    return signed.signature.hex()


def get_agents():
    print("\n========================================")
    print("ASTER TESTNET - AGENT CHECK")
    print("========================================")

    server_time_ms = get_server_time_ms()

    nonce = get_nonce(server_time_ms)

    params = {
        "user": USER_ADDRESS,
        "signer": API_WALLET,
        "nonce": nonce,
    }

    # IMPORTANT:
    # The exact query string below is what gets signed.
    query_string = canonical_query(params)

    signature = sign_message(query_string)

    final_query = query_string + "&signature=" + urllib.parse.quote(
        signature,
        safe=""
    )

    url = f"{BASE_URL}/fapi/v3/agent?{final_query}"

    print("\nUSER:")
    print(USER_ADDRESS)

    print("\nSIGNER:")
    print(API_WALLET)

    print("\nCHAIN ID:")
    print(CHAIN_ID)

    print("\nSIGNED QUERY:")
    print(query_string)

    print("\nCalling:")
    print("GET /fapi/v3/agent")

    try:
        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "Aster-Testnet-Agent-Diagnostic/1.0"
            }
        )
    except requests.RequestException as e:
        fail(f"Network error:\n{e}")

    print("\nHTTP STATUS:")
    print(response.status_code)

    print("\nRAW RESPONSE:")
    print(response.text)

    if response.status_code != 200:
        print("\n========================================")
        print("AGENT CHECK FAILED")
        print("========================================")
        print("The Testnet API did not accept the Agent query.")
        return

    try:
        data = response.json()
    except ValueError:
        print("\nResponse was not valid JSON.")
        return

    print("\n========================================")
    print("AGENT CHECK RESULT")
    print("========================================")

    if not isinstance(data, list):
        print(data)
        return

    if len(data) == 0:
        print("No authorized agents were returned.")
        print("\nThis means the Testnet API did not return any")
        print("authorized Agent for this user.")
        return

    print(f"Authorized agents returned: {len(data)}")

    found = False

    for index, agent in enumerate(data, start=1):
        print(f"\n--- Agent {index} ---")

        print("Address:", agent.get("agentAddress"))
        print("Name:", agent.get("agentName"))
        print("Read:", agent.get("canRead"))
        print("Perp:", agent.get("canPerpTrade"))
        print("Spot:", agent.get("canSpotTrade"))
        print("Withdraw:", agent.get("canWithdraw"))
        print("IP:", agent.get("ipWhitelist"))
        print("Expired:", agent.get("expired"))
        print("Source:", agent.get("source"))

        agent_address = agent.get("agentAddress", "")

        if normalize_address(agent_address) == normalize_address(API_WALLET):
            found = True

            print("\n>>> THIS IS OUR API WALLET <<<")

            if agent.get("canPerpTrade") is True:
                print(">>> Perp trading permission: YES")
            else:
                print(">>> Perp trading permission: NO")

    print("\n========================================")

    if found:
        print("RESULT: OUR SIGNER WAS FOUND")
        print("========================================")
        print(
            "The Testnet API recognizes our signer as an Agent."
        )
    else:
        print("RESULT: OUR SIGNER WAS NOT FOUND")
        print("========================================")
        print(
            "The Testnet API did not return our signer "
            "as an authorized Agent."
        )


def main():
    print("ASTER FUTURES V3 TESTNET")
    print("AGENT DIAGNOSTIC - NO TRADING")

    if not API_WALLET:
        fail("ASTER_API_WALLET is missing.")

    if not PRIVATE_KEY:
        fail("ASTER_API_PRIVATE_KEY is missing.")

    if not USER_ADDRESS:
        fail("ASTER_USER_ADDRESS is missing.")

    validate_address("ASTER_API_WALLET", API_WALLET)
    validate_address("ASTER_USER_ADDRESS", USER_ADDRESS)

    # Verify that the private key actually belongs to API_WALLET.
    try:
        derived_address = Account.from_key(PRIVATE_KEY).address
    except Exception as e:
        fail(f"Could not load API private key:\n{e}")

    print("\nConfigured API wallet:")
    print(API_WALLET)

    print("\nDerived signer from private key:")
    print(derived_address)

    if normalize_address(derived_address) != normalize_address(API_WALLET):
        fail(
            "\nPRIVATE KEY / API WALLET MISMATCH.\n"
            "The private key in Railway does not belong to "
            "ASTER_API_WALLET."
        )

    print("\nSigner check: OK")

    get_agents()


if __name__ == "__main__":
    main()
