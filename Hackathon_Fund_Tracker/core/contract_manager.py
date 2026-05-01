import json
import os
from pathlib import Path
from web3 import Web3

# ── Solc version ──────────────────────────────────────────────
_SOLC_VERSION = "0.8.0"
_COMPILED_JSON = Path(__file__).parent.parent / "contracts" / "FundVault.json"


def get_raw_tx(signed_txn):
    try:
        return signed_txn.raw_transaction
    except AttributeError:
        return signed_txn.rawTransaction


def _load_precompiled() -> tuple:
    """Load ABI + bytecode from the pre-compiled JSON artifact."""
    if _COMPILED_JSON.exists():
        data = json.loads(_COMPILED_JSON.read_text())
        return data["abi"], data["bytecode"]
    raise FileNotFoundError(f"Pre-compiled artifact not found at {_COMPILED_JSON}")


def compile_contract(contract_path) -> tuple:
    """
    Compile FundVault.sol using py-solc-x.
    Falls back to the pre-compiled FundVault.json if solcx is unavailable
    or if compilation fails (e.g. solc not downloaded yet).
    """
    try:
        from solcx import compile_standard, install_solc, get_installed_solc_versions
        import packaging.version  # comes with py-solc-x

        need_ver = packaging.version.Version(_SOLC_VERSION)

        # Only install if not already present — avoids the 10-20 s freeze on repeat runs
        installed = [packaging.version.Version(str(v))
                     for v in get_installed_solc_versions()]
        if need_ver not in installed:
            print(f"[COMPILE] Installing solc {_SOLC_VERSION} (one-time, ~5 MB)…")
            install_solc(_SOLC_VERSION)

        with open(contract_path, "r") as f:
            source = f.read()

        print("[COMPILE] Compiling FundVault.sol…")
        compiled = compile_standard(
            {
                "language": "Solidity",
                "sources": {os.path.basename(contract_path): {"content": source}},
                "settings": {
                    "outputSelection": {
                        "*": {"*": ["abi", "metadata", "evm.bytecode", "evm.bytecode.sourceMap"]}
                    }
                },
            },
            solc_version=_SOLC_VERSION,
        )

        name = os.path.basename(contract_path).split(".")[0]
        iface = compiled["contracts"][os.path.basename(contract_path)][name]
        abi      = iface["abi"]
        bytecode = iface["evm"]["bytecode"]["object"]

        # Cache to disk so subsequent runs skip recompile
        _COMPILED_JSON.write_text(json.dumps({"abi": abi, "bytecode": bytecode}, indent=2))
        print("[COMPILE] Compilation successful — cached to FundVault.json")
        return abi, bytecode

    except Exception as exc:
        print(f"[COMPILE] solcx unavailable ({exc}) — loading pre-compiled artifact.")
        return _load_precompiled()


def deploy_contract(w3: Web3, private_key: str, abi: list, bytecode: str) -> str:
    print("[DEPLOY] Deploying FundVault…")
    account = w3.eth.account.from_key(private_key)
    FundVault = w3.eth.contract(abi=abi, bytecode=bytecode)
    nonce = w3.eth.get_transaction_count(account.address)
    tx = FundVault.constructor().build_transaction({
        "chainId":   w3.eth.chain_id,
        "gasPrice":  w3.eth.gas_price,
        "from":      account.address,
        "nonce":     nonce,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(get_raw_tx(signed)))
    addr = receipt.contractAddress or receipt["contractAddress"]
    print(f"[DEPLOY] Contract deployed at {addr}")
    return addr


def deposit_funds(w3: Web3, private_key: str, contract, amount_eth: float):
    account = w3.eth.account.from_key(private_key)
    nonce   = w3.eth.get_transaction_count(account.address)
    tx = contract.functions.depositFunds().build_transaction({
        "chainId":  w3.eth.chain_id,
        "gasPrice": w3.eth.gas_price,
        "from":     account.address,
        "nonce":    nonce,
        "value":    w3.to_wei(amount_eth, "ether"),
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(get_raw_tx(signed)))
    print(f"[CONTRACT] Deposited {amount_eth} ETH.")


def create_escrow(w3: Web3, private_key: str, contract, vendor_address: str,
                  amount_eth: float, lock_duration_sec: int) -> int:
    account    = w3.eth.account.from_key(private_key)
    nonce      = w3.eth.get_transaction_count(account.address)
    amount_wei = w3.to_wei(amount_eth, "ether")
    tx = contract.functions.createEscrow(
        vendor_address, amount_wei, lock_duration_sec
    ).build_transaction({
        "chainId":  w3.eth.chain_id,
        "gasPrice": w3.eth.gas_price,
        "from":     account.address,
        "nonce":    nonce,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(get_raw_tx(signed)))
    escrow_id = contract.functions.escrowCounter().call() - 1
    print(f"[CONTRACT] Escrow #{escrow_id} created for {vendor_address}.")
    return escrow_id


def freeze_transaction(w3: Web3, auditor_private_key: str, contract, escrow_id: int):
    account = w3.eth.account.from_key(auditor_private_key)
    nonce   = w3.eth.get_transaction_count(account.address)
    tx = contract.functions.freezeTransaction(escrow_id).build_transaction({
        "chainId":  w3.eth.chain_id,
        "gasPrice": w3.eth.gas_price,
        "from":     account.address,
        "nonce":    nonce,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=auditor_private_key)
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(get_raw_tx(signed)))
    print(f"[CONTRACT] Escrow #{escrow_id} frozen.")


def vote_on_escrow(w3: Web3, auditor_private_key: str, contract,
                   escrow_id: int, vote_type: str = "unfreeze"):
    account = w3.eth.account.from_key(auditor_private_key)
    nonce   = w3.eth.get_transaction_count(account.address)
    fn = (contract.functions.voteToUnfreeze if vote_type == "unfreeze"
          else contract.functions.voteToCancel)
    tx = fn(escrow_id).build_transaction({
        "chainId":  w3.eth.chain_id,
        "gasPrice": w3.eth.gas_price,
        "from":     account.address,
        "nonce":    nonce,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=auditor_private_key)
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(get_raw_tx(signed)))
    print(f"[CONTRACT] Voted to {vote_type} escrow #{escrow_id}.")


def add_auditor(w3: Web3, owner_private_key: str, contract, new_auditor_address: str):
    account = w3.eth.account.from_key(owner_private_key)
    nonce   = w3.eth.get_transaction_count(account.address)
    tx = contract.functions.addAuditor(new_auditor_address).build_transaction({
        "chainId":  w3.eth.chain_id,
        "gasPrice": w3.eth.gas_price,
        "from":     account.address,
        "nonce":    nonce,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=owner_private_key)
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(get_raw_tx(signed)))
    print(f"[CONTRACT] Auditor {new_auditor_address} added.")
