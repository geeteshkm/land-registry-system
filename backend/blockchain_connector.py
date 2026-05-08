from web3 import Web3
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path
import os
import json

PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=PROJECT_DIR / ".env")

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────

RPC_URL          = os.getenv("SEPOLIA_RPC_URL")
PRIVATE_KEY      = os.getenv("PRIVATE_KEY")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS")

BLOCKCHAIN_ENABLED = True
contract = None
w3 = None
GOVERNMENT_ACCOUNT = None

if not all([RPC_URL, PRIVATE_KEY, CONTRACT_ADDRESS]):
    BLOCKCHAIN_ENABLED = False
    print("[WARN] Blockchain env vars missing. Blockchain endpoints are disabled until SEPOLIA_RPC_URL, PRIVATE_KEY, and CONTRACT_ADDRESS are configured.")
else:
    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 5}))
    CONTRACT_ADDRESS      = Web3.to_checksum_address(CONTRACT_ADDRESS)
    GOVERNMENT_ACCOUNT    = w3.eth.account.from_key(PRIVATE_KEY).address
    print(f"[OK] Blockchain module initialized | Gov wallet: {GOVERNMENT_ACCOUNT}")


def _ensure_blockchain_ready():
    if not BLOCKCHAIN_ENABLED or contract is None or w3 is None or GOVERNMENT_ACCOUNT is None:
        raise EnvironmentError(
            "Blockchain functionality is disabled. Set SEPOLIA_RPC_URL, PRIVATE_KEY, CONTRACT_ADDRESS and ensure RPC connectivity."
        )
    if not w3.is_connected():
        raise EnvironmentError(
            "Cannot connect to blockchain RPC. Check SEPOLIA_RPC_URL and network connectivity."
        )

# ─────────────────────────────────────────
# CONTRACT ABI
# ─────────────────────────────────────────

CONTRACT_ABI = [
    # governmentAuthority
    {
        "inputs": [],
        "name": "governmentAuthority",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    # registerProperty
    {
        "inputs": [
            {"internalType": "uint256", "name": "propertyId",      "type": "uint256"},
            {"internalType": "string",  "name": "propertyAddress",  "type": "string"},
            {"internalType": "uint256", "name": "price",            "type": "uint256"},
            {"internalType": "address", "name": "ownerAddress",     "type": "address"}
        ],
        "name": "registerProperty",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # transferProperty
    {
        "inputs": [
            {"internalType": "uint256", "name": "propertyId", "type": "uint256"},
            {"internalType": "address", "name": "newOwner",   "type": "address"},
            {"internalType": "uint256", "name": "price",      "type": "uint256"}
        ],
        "name": "transferProperty",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # raiseDispute
    {
        "inputs": [{"internalType": "uint256", "name": "propertyId", "type": "uint256"}],
        "name": "raiseDispute",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # resolveDispute
    {
        "inputs": [{"internalType": "uint256", "name": "propertyId", "type": "uint256"}],
        "name": "resolveDispute",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # getPropertyOwner
    {
        "inputs": [{"internalType": "uint256", "name": "propertyId", "type": "uint256"}],
        "name": "getPropertyOwner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    # getPropertyDetails
    {
        "inputs": [{"internalType": "uint256", "name": "propertyId", "type": "uint256"}],
        "name": "getPropertyDetails",
        "outputs": [{
            "components": [
                {"internalType": "uint256", "name": "propertyId",      "type": "uint256"},
                {"internalType": "address", "name": "currentOwner",    "type": "address"},
                {"internalType": "string",  "name": "propertyAddress", "type": "string"},
                {"internalType": "uint256", "name": "price",           "type": "uint256"},
                {"internalType": "bool",    "name": "isVerified",      "type": "bool"},
                {"internalType": "bool",    "name": "isDisputed",      "type": "bool"},
                {"internalType": "uint256", "name": "createdAt",       "type": "uint256"},
                {"internalType": "uint256", "name": "updatedAt",       "type": "uint256"}
            ],
            "internalType": "struct LandRegistry.Property",
            "name": "",
            "type": "tuple"
        }],
        "stateMutability": "view",
        "type": "function"
    },
    # getPropertyHistory
    {
        "inputs": [{"internalType": "uint256", "name": "propertyId", "type": "uint256"}],
        "name": "getPropertyHistory",
        "outputs": [{
            "components": [
                {"internalType": "uint256", "name": "transactionId", "type": "uint256"},
                {"internalType": "uint256", "name": "propertyId",    "type": "uint256"},
                {"internalType": "address", "name": "sender",        "type": "address"},
                {"internalType": "address", "name": "receiver",      "type": "address"},
                {"internalType": "uint256", "name": "price",         "type": "uint256"},
                {"internalType": "uint256", "name": "timestamp",     "type": "uint256"},
                {"internalType": "string",  "name": "txType",        "type": "string"}
            ],
            "internalType": "struct LandRegistry.Transaction[]",
            "name": "",
            "type": "tuple[]"
        }],
        "stateMutability": "view",
        "type": "function"
    },
    # verifyProperty
    {
        "inputs": [{"internalType": "uint256", "name": "propertyId", "type": "uint256"}],
        "name": "verifyProperty",
        "outputs": [
            {"internalType": "bool",    "name": "isVerified", "type": "bool"},
            {"internalType": "bool",    "name": "isDisputed", "type": "bool"},
            {"internalType": "address", "name": "owner",      "type": "address"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    # getOwnerProperties
    {
        "inputs": [{"internalType": "address", "name": "owner", "type": "address"}],
        "name": "getOwnerProperties",
        "outputs": [{"internalType": "uint256[]", "name": "", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function"
    },
    # getPropertyAuditTrail
    {
        "inputs": [{"internalType": "uint256", "name": "propertyId", "type": "uint256"}],
        "name": "getPropertyAuditTrail",
        "outputs": [{
            "components": [
                {"internalType": "uint256", "name": "propertyId", "type": "uint256"},
                {"internalType": "uint256", "name": "transactionIndex", "type": "uint256"},
                {"internalType": "bytes32", "name": "currentDataHash", "type": "bytes32"},
                {"internalType": "bytes32", "name": "previousDataHash", "type": "bytes32"},
                {"internalType": "bytes32", "name": "blockFingerprint", "type": "bytes32"},
                {"internalType": "uint256", "name": "timestamp", "type": "uint256"},
                {"internalType": "address", "name": "actor", "type": "address"},
                {"internalType": "string", "name": "action", "type": "string"}
            ],
            "internalType": "struct LandRegistry.AuditRecord[]",
            "name": "",
            "type": "tuple[]"
        }],
        "stateMutability": "view",
        "type": "function"
    },
    # totalProperties
    {
        "inputs": [],
        "name": "totalProperties",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    # totalTransactions
    {
        "inputs": [],
        "name": "totalTransactions",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
]

if BLOCKCHAIN_ENABLED and w3 is not None:
    contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)
else:
    contract = None


# ─────────────────────────────────────────
# INTERNAL: SEND TRANSACTION
# ─────────────────────────────────────────

def _send_tx(fn):
    """Build, sign, and send a contract transaction. Returns tx_hash hex."""
    _ensure_blockchain_ready()
    nonce = w3.eth.get_transaction_count(GOVERNMENT_ACCOUNT)
    tx_params = {
        "from": GOVERNMENT_ACCOUNT,
        "nonce": nonce,
        "gasPrice": w3.to_wei("10", "gwei"),
    }

    # Preflight the call so contract reverts surface with a useful reason.
    try:
        estimated_gas = fn.estimate_gas({"from": GOVERNMENT_ACCOUNT})
    except Exception as e:
        raise Exception(f"Contract preflight failed: {e}")

    tx = fn.build_transaction({
        **tx_params,
        "gas": max(300_000, int(estimated_gas * 1.2)),
    })

    signed  = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    if raw_tx is None:
        raise AttributeError("Signed transaction is missing raw transaction bytes")
    tx_hash = w3.eth.send_raw_transaction(raw_tx)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

    if receipt.status != 1:
        raise Exception(f"Blockchain transaction failed. Hash: {tx_hash.hex()}")

    return tx_hash.hex()


# ─────────────────────────────────────────
# REGISTER PROPERTY ON CHAIN
# ─────────────────────────────────────────

def register_property_on_chain(
    property_id: int,
    address_text: str,
    price: int,
    owner_wallet: str,
) -> str:
    _ensure_blockchain_ready()
    owner_wallet = Web3.to_checksum_address(owner_wallet)
    fn = contract.functions.registerProperty(
        property_id,
        address_text,
        price,
        owner_wallet,
    )
    return _send_tx(fn)


# ─────────────────────────────────────────
# TRANSFER PROPERTY ON CHAIN
# ─────────────────────────────────────────

def transfer_property_on_chain(
    property_id: int,
    new_owner_wallet: str,
    price: int,
) -> str:
    """Government wallet signs the transfer on behalf of the owner."""
    _ensure_blockchain_ready()
    new_owner_wallet = Web3.to_checksum_address(new_owner_wallet)
    fn = contract.functions.transferProperty(
        property_id,
        new_owner_wallet,
        price,
    )
    return _send_tx(fn)


# ─────────────────────────────────────────
# RAISE DISPUTE ON CHAIN
# ─────────────────────────────────────────

def raise_dispute_on_chain(property_id: int) -> str:
    _ensure_blockchain_ready()
    fn = contract.functions.raiseDispute(property_id)
    return _send_tx(fn)


# ─────────────────────────────────────────
# RESOLVE DISPUTE ON CHAIN
# ─────────────────────────────────────────

def resolve_dispute_on_chain(property_id: int) -> str:
    _ensure_blockchain_ready()
    fn = contract.functions.resolveDispute(property_id)
    return _send_tx(fn)


# ─────────────────────────────────────────
# READ: OWNER
# ─────────────────────────────────────────

def get_property_owner_from_chain(property_id: int) -> str:
    _ensure_blockchain_ready()
    return contract.functions.getPropertyOwner(property_id).call()


# ─────────────────────────────────────────
# READ: FULL HISTORY
# ─────────────────────────────────────────

def get_property_history_from_chain(property_id: int) -> list:
    _ensure_blockchain_ready()
    raw = contract.functions.getPropertyHistory(property_id).call()
    result = []
    for txn in raw:
        result.append({
            "transaction_id": txn[0],
            "property_id":    txn[1],
            "from":           txn[2],
            "to":             txn[3],
            "price":          txn[4],
            "timestamp":      txn[5],
            "tx_type":        txn[6],
            "readable_time":  datetime.fromtimestamp(txn[5]).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return result


def get_property_details_from_chain(property_id: int) -> dict:
    _ensure_blockchain_ready()
    raw = contract.functions.getPropertyDetails(property_id).call()
    return {
        "property_id": raw[0],
        "current_owner": raw[1],
        "property_address": raw[2],
        "price": raw[3],
        "is_verified": raw[4],
        "is_disputed": raw[5],
        "created_at": raw[6],
        "updated_at": raw[7],
        "created_at_readable": datetime.fromtimestamp(raw[6]).strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at_readable": datetime.fromtimestamp(raw[7]).strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_property_audit_trail_from_chain(property_id: int) -> list:
    _ensure_blockchain_ready()
    raw = contract.functions.getPropertyAuditTrail(property_id).call()
    result = []
    for record in raw:
        result.append({
            "property_id": record[0],
            "transaction_index": record[1],
            "current_data_hash": record[2].hex() if hasattr(record[2], "hex") else str(record[2]),
            "previous_data_hash": record[3].hex() if hasattr(record[3], "hex") else str(record[3]),
            "block_fingerprint": record[4].hex() if hasattr(record[4], "hex") else str(record[4]),
            "timestamp": record[5],
            "readable_time": datetime.fromtimestamp(record[5]).strftime("%Y-%m-%d %H:%M:%S"),
            "actor": record[6],
            "action": record[7],
        })
    return result


# ─────────────────────────────────────────
# READ: VERIFY PROPERTY
# ─────────────────────────────────────────

def verify_property_on_chain(property_id: int) -> dict:
    _ensure_blockchain_ready()
    is_verified, is_disputed, owner = contract.functions.verifyProperty(property_id).call()
    return {
        "is_verified": is_verified,
        "is_disputed": is_disputed,
        "owner":       owner,
    }


# ─────────────────────────────────────────
# READ: STATS
# ─────────────────────────────────────────

def get_chain_stats() -> dict:
    _ensure_blockchain_ready()
    return {
        "total_properties":   contract.functions.totalProperties().call(),
        "total_transactions": contract.functions.totalTransactions().call(),
        "government_address": contract.functions.governmentAuthority().call(),
        "signer_address":     GOVERNMENT_ACCOUNT,
        "contract_address":   CONTRACT_ADDRESS,
    }
