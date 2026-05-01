# ============================================================
#  config.py — Ledger Nexus Global Configuration
#  Secrets are loaded from .env (never commit that file).
#  All values fall back to safe demo defaults if .env is absent.
# ============================================================

import os
from pathlib import Path

# Load .env from project root (silently ignored if not present)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass  # python-dotenv not installed — use OS env / defaults only

# ── Pinata / IPFS ─────────────────────────────────────────────
PINATA_JWT        = os.environ.get("PINATA_JWT", "YOUR_PINATA_JWT_HERE")
PINATA_UPLOAD_URL = "https://api.pinata.cloud/pinning/pinFileToIPFS"
PINATA_GATEWAY    = "https://gateway.pinata.cloud/ipfs/"

# ── Ethereum provider ─────────────────────────────────────────
# Empty string → auto-select (Ganache → PyEVM in-memory fallback)
ETH_PROVIDER_URL = os.environ.get("ETH_PROVIDER_URL", "")

# ── ANSX Relay ────────────────────────────────────────────────
ANSX_RELAY_URL = os.environ.get("ANSX_RELAY_URL", "https://ansxvault.onrender.com")

# ── KYC Oracle Keys ───────────────────────────────────────────
# In a real setup, this is the securely isolated backend key
KYC_ORACLE_PRIVATE_KEY = "0x1111111111111111111111111111111111111111111111111111111111111111"

# ── Watchdog thresholds ────────────────────────────────────────
AMOUNT_FLAG_THRESHOLD   = 100_000   # flag any tx above this (ETH)
RAPID_TX_WINDOW_SECONDS = 60        # flag if >3 tx in this window
UNVERIFIED_CONTRACTORS  = [         # known-bad addresses (mock)
    "0xDEADBEEF00000000000000000000000000000001",
    "0xBAD0000000000000000000000000000000000BAD",
]

# ── UI constants ───────────────────────────────────────────────
APP_TITLE        = "LEDGER NEXUS"
APP_VERSION      = "1.0.0"
WINDOW_WIDTH     = 1280
WINDOW_HEIGHT    = 800
WATCHDOG_VERSION = "1.0.0"

# ── Report output dir (relative to core/ script location) ─────
REPORT_OUTPUT_DIR = str(Path(__file__).parent / "reports")

# ────────────────────────────────────────────────────────────────────────────
#  NFC AUTHORITY REGISTRY
#  ─────────────────────────────────────────────────────────────────────────
#  Each entry maps a clipboard string (what the iPhone Shortcut sends)
#  to a human-readable authority name and their permission tier.
#
#  HOW TO CONFIGURE AN NFC TAG (iPhone Shortcut method):
#    1. Open Shortcuts app on iPhone
#    2. Create a new Shortcut named after the authority (e.g. "Finance Secretary")
#    3. Add action: "Text" → type the EXACT UID string below
#    4. Add action: "Copy to Clipboard"
#    5. Add automation: "When NFC Tag is scanned" → select tag → run this Shortcut
#    6. Write the authority's name on the physical tag with a marker
#
#  TIER MEANINGS:
#    "ADMIN"   — Can create escrows, register vendors, set budgets. Full control.
#    "SIGNER"  — Can only cast multi-sig approval votes. Cannot create escrows.
#    "AUDITOR" — Can freeze transactions, submit milestone certificates, read reports.
#    "PUBLIC"  — Read-only public ledger access. No NFC needed.
# ────────────────────────────────────────────────────────────────────────────

NFC_AUTHORITY_REGISTRY = {
    # ── Administrator (Fund Management) ──────────────────────────────────
    "ANSX-UID:Admin_Tag_001": {
        "name":   "Chief Finance Officer",
        "role":   "ADMIN",
        "color":  "#7b2fff",
        "badge":  "CFO",
        "desc":   "Creates escrows, registers vendors, manages budget heads.",
    },

    # ── Multi-Sig Signers (Approval Quorum) ──────────────────────────────
    # These people ONLY approve or reject — they cannot create transactions.
    # The contract requires requiredApprovals (default: 2) before any release.
    "ANSX-UID:Signer_Tag_001": {
        "name":   "Finance Secretary",
        "role":   "SIGNER",
        "color":  "#ff6b35",
        "badge":  "FIN-SEC",
        "desc":   "Multi-sig signer. Approves or rejects fund releases.",
    },
    "ANSX-UID:Signer_Tag_002": {
        "name":   "Treasury Officer",
        "role":   "SIGNER",
        "color":  "#ff6b35",
        "badge":  "TREAS",
        "desc":   "Multi-sig signer. Approves or rejects fund releases.",
    },
    "ANSX-UID:Signer_Tag_003": {
        "name":   "Department Secretary",
        "role":   "SIGNER",
        "color":  "#ff6b35",
        "badge":  "DEPT-SEC",
        "desc":   "Multi-sig signer. Approves or rejects fund releases.",
    },

    # ── Auditor (Independent Oversight) ──────────────────────────────────
    "ANSX-UID:Auditor_Tag_001": {
        "name":   "Senior Auditor",
        "role":   "AUDITOR",
        "color":  "#00f5ff",
        "badge":  "AUDR",
        "desc":   "Freezes suspicious transactions, submits milestone certificates.",
    },
}

# ── Legacy aliases (keep backward-compat with old code) ──────────────────
NFC_UID_ADMIN   = "ANSX-UID:Admin_Tag_001"
NFC_UID_AUDITOR = "ANSX-UID:Auditor_Tag_001"

# All signer UIDs (for on-chain registration)
NFC_SIGNER_UIDS = [
    "ANSX-UID:Signer_Tag_001",
    "ANSX-UID:Signer_Tag_002",
    "ANSX-UID:Signer_Tag_003",
]


def resolve_authority(uid_string: str) -> dict:
    """
    Given a raw clipboard string (e.g. 'ANSX-UID:Signer_Tag_001'),
    return the authority dict, or PUBLIC default if unknown.
    """
    return NFC_AUTHORITY_REGISTRY.get(uid_string, {
        "name":  "Public Observer",
        "role":  "PUBLIC",
        "color": "#00ff88",
        "badge": "PUB",
        "desc":  "Read-only access to the public ledger.",
    })
