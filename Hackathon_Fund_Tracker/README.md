# ◈ A.N.SXVault — Public Funds Tracker

A hardware-entangled, decentralized ledger dashboard designed for a cybersecurity and blockchain hackathon. The system replaces standard password/wallet logins with a physically bound iOS NFC Universal Clipboard workflow.

---

## ⚡ Features

- **Hardware Entangled Auth:** Uses macOS universal clipboard to read an encrypted NFC UID sent from an iPhone Shortcut. Web3 keys are mathematically derived in volatile RAM and never touch the disk.
- **Role-Based Access Control:** Pre-configured roles (`ADMIN`, `AUDITOR`, `PUBLIC`) simulated via demo launcher or linked to specific NFC hardware tags.
- **Smart Contract Escrow:** (`contracts/FundVault.sol`) Funds are held in a time-locked escrow. Auditors can vote to freeze or cancel suspicious transactions.
- **IPFS Watchdog Daemon:** Anomalous transactions automatically generate an AES-256-GCM encrypted audit report that is permanently pinned to IPFS (via Pinata). Physical hardware keys are required to decrypt the report.
- **In-Memory Blockchain:** Automatically sets up an in-memory `PyEVM` testnet so the demo works completely offline/without an external RPC.

## 🚀 Quick Start

Run the one-click launch script to install dependencies in a local virtual environment and launch the UI:

```bash
./run.sh
```

*(Alternatively: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python3 nexus_launcher.py`)*

---

## 📱 Hardware NFC Setup (iPhone Shortcuts)

The app "taps" an NFC card by reading the macOS Universal Clipboard.

1. Open the **Shortcuts app** on your iPhone.
2. Create a new Shortcut for the **Admin** tag:
   - Action 1: `Text` → Paste: `ANSX-UID:Admin_Tag_001`
   - Action 2: `Copy to Clipboard`
3. Create a second Shortcut for the **Auditor** tag:
   - Action 1: `Text` → Paste: `ANSX-UID:Auditor_Tag_002`
   - Action 2: `Copy to Clipboard`

> **Usage:** In the Ledger Nexus app, click "Re-authenticate" (or trigger a fund transfer). You will have 30 seconds to run the iPhone shortcut. Apple's Universal Clipboard will beam the text to your Mac, and the Python app will decrypt the Web3 key!

## ⚙️ Configuration

Copy `.env.example` to `.env` to configure your API keys.

- `PINATA_JWT`: Your Pinata API token. If omitted, the watchdog daemon will generate "mock" IPFS CIDs so the demo UI continues to function perfectly offline.
- `ETH_PROVIDER_URL`: Provide an RPC URL (like Infura or Ganache `http://127.0.0.1:8545`). If omitted, the app spins up a local in-memory blockchain using `eth-tester[pyevm]`.

---

## 🛠 Project Structure

- `demo_launcher.py`: Bootstrapper splash screen for hackathon mode.
- `ui/ui_dashboard.py`: Core PyQt5 UI, state management, and blockchain queries.
- `core/watchdog_daemon.py`: Logic for analyzing TXs, encrypting JSON reports, and uploading to IPFS.
- `core/nfc_wallet.py`: Interfaces with the macOS clipboard to securely poll for iPhone NFC data.
- `core/contract_manager.py`: Handles `py-solc-x` Solidity compilation and deployment.
- `contracts/FundVault.sol`: Core Escrow smart contract.
