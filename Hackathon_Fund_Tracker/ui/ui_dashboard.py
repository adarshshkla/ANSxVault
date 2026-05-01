# ============================================================
#  ui_dashboard.py — Ledger Nexus Desktop Interface
#
#  Stack  : PyQt5, pure Python
#  Theme  : Cyberpunk dark (neon cyan / electric purple)
#  Panels : Public Feed · Admin Panel · Auditor Panel
# ============================================================

import sys
import os
import json
import random
import threading
from datetime import datetime, timedelta, timezone

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QFrame, QLineEdit,
    QFormLayout, QStackedWidget, QTextEdit, QSizePolicy, QSpacerItem,
    QGraphicsDropShadowEffect, QProgressDialog
)
from PyQt5.QtGui import (
    QFont, QColor, QPalette, QLinearGradient, QPainter,
    QBrush, QPen, QGradient
)
from PyQt5.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QPropertyAnimation,
    QEasingCurve, QRect, QPoint, pyqtProperty
)

# Add core directory to python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

try:
    import nfc_wallet
    import contract_manager
    from web3 import Web3
except ImportError as _e:
    print(f"[WARN] Import warning: {_e}")

# ─── Global State ───────────────────────────────────────────────────────
CURRENT_PRIVATE_KEY    = None
CURRENT_ROLE           = "PUBLIC"
CURRENT_COLOR          = "#00ff88"
CURRENT_AUTHORITY_NAME = "Public Observer"   # human name of whoever tapped
CURRENT_AUTHORITY_BADGE = "PUB"              # short badge e.g. CFO, FIN-SEC
W3_INSTANCE            = None
CONTRACT_INSTANCE      = None
OWNER_ADDRESS          = None

# Internal transaction list (replaces fake mock generator)
REAL_TRANSACTIONS = []

def _resolve_role_on_chain(w3, contract, private_key, raw_uid: str = ""):
    """
    Resolve role from:
    1. NFC Authority Registry (uid string → role)
    2. On-chain contract checks as fallback
    Returns (role, color, authority_name, badge)
    """
    global CURRENT_AUTHORITY_NAME, CURRENT_AUTHORITY_BADGE

    if not private_key:
        CURRENT_AUTHORITY_NAME  = "Public Observer"
        CURRENT_AUTHORITY_BADGE = "PUB"
        return "PUBLIC", "#00ff88"

    # 1. Registry lookup by raw UID string (most reliable)
    if raw_uid:
        from config import resolve_authority
        auth = resolve_authority(raw_uid)
        CURRENT_AUTHORITY_NAME  = auth["name"]
        CURRENT_AUTHORITY_BADGE = auth["badge"]
        return auth["role"], auth["color"]

    # 2. On-chain fallback (when UID not available, e.g. session resume)
    user_address = w3.eth.account.from_key(private_key).address

    if OWNER_ADDRESS and user_address.lower() == OWNER_ADDRESS.lower():
        CURRENT_AUTHORITY_NAME  = "Chief Finance Officer"
        CURRENT_AUTHORITY_BADGE = "CFO"
        return "ADMIN", "#7b2fff"

    try:
        if contract.functions.auditors(user_address).call():
            CURRENT_AUTHORITY_NAME  = "Senior Auditor"
            CURRENT_AUTHORITY_BADGE = "AUDR"
            return "AUDITOR", "#00f5ff"
    except Exception:
        pass

    CURRENT_AUTHORITY_NAME  = "Authenticated User"
    CURRENT_AUTHORITY_BADGE = "USER"
    return "USER", "#ffaa00"


def _init_web3():
    """Initialise Web3, deploy contract, seed treasury and transactions."""
    global W3_INSTANCE, CONTRACT_INSTANCE, OWNER_ADDRESS
    global CURRENT_ROLE, CURRENT_COLOR, REAL_TRANSACTIONS

    if W3_INSTANCE is not None:
        return True

    try:
        from config import ETH_PROVIDER_URL, NFC_UID_ADMIN, NFC_UID_AUDITOR

        if ETH_PROVIDER_URL:
            w3 = Web3(Web3.HTTPProvider(ETH_PROVIDER_URL))
        else:
            w3 = Web3(Web3.HTTPProvider('http://127.0.0.1:8545'))

        if not w3.is_connected():
            from eth_tester import EthereumTester, PyEVMBackend
            tester = EthereumTester(PyEVMBackend())
            w3 = Web3(Web3.EthereumTesterProvider(tester))
            print("[WEB3] Using in-memory PyEVM testnet.")
        else:
            print("[WEB3] Connected to external node.")

        coinbase     = w3.eth.accounts[0]
        from config import NFC_UID_ADMIN, NFC_UID_AUDITOR, NFC_SIGNER_UIDS, NFC_AUTHORITY_REGISTRY
        admin_key    = nfc_wallet.derive_web3_private_key(NFC_UID_ADMIN.replace("ANSX-UID:", ""))
        auditor_key  = nfc_wallet.derive_web3_private_key(NFC_UID_AUDITOR.replace("ANSX-UID:", ""))
        admin_addr   = w3.eth.account.from_key(admin_key).address
        auditor_addr = w3.eth.account.from_key(auditor_key).address

        # Derive all signer addresses
        signer_addrs = []
        for uid in NFC_SIGNER_UIDS:
            key  = nfc_wallet.derive_web3_private_key(uid.replace("ANSX-UID:", ""))
            addr = w3.eth.account.from_key(key).address
            signer_addrs.append((uid, addr))

        # Store admin address for role resolution
        OWNER_ADDRESS = admin_addr

        # Deploy via coinbase
        contract_path = os.path.join(os.path.dirname(__file__), '..', 'contracts', 'FundVault.sol')
        abi, bytecode = contract_manager.compile_contract(contract_path)
        FundVault = w3.eth.contract(abi=abi, bytecode=bytecode)
        receipt   = w3.eth.wait_for_transaction_receipt(
            FundVault.constructor().transact({"from": coinbase})
        )
        inst = w3.eth.contract(address=receipt.contractAddress, abi=abi)

        # Seed treasury
        inst.functions.depositFunds().transact({"from": coinbase, "value": w3.to_wei(500_000, "ether")})

        # Register auditor
        inst.functions.addAuditor(auditor_addr).transact({"from": coinbase})
        auth_info = NFC_AUTHORITY_REGISTRY.get(NFC_UID_AUDITOR, {})
        print(f"[CONTRACT] Auditor '{auth_info.get('name','Senior Auditor')}' ({auditor_addr[:12]}…) registered.")

        # Register all signers as auditors on-chain (they can call approveRelease)
        for uid, addr in signer_addrs:
            inst.functions.addAuditor(addr).transact({"from": coinbase})
            signer_info = NFC_AUTHORITY_REGISTRY.get(uid, {})
            print(f"[CONTRACT] Signer '{signer_info.get('name','Signer')}' ({addr[:12]}…) registered.")

        # Set KYC Oracle Address
        from config import KYC_ORACLE_PRIVATE_KEY
        oracle_addr = w3.eth.account.from_key(KYC_ORACLE_PRIVATE_KEY).address
        inst.functions.setKycOracle(oracle_addr).transact({"from": coinbase})
        print(f"[CONTRACT] ZK-KYC Oracle Set: {oracle_addr[:12]}…")

        W3_INSTANCE       = w3
        CONTRACT_INSTANCE = inst

        # Resolve current session role
        CURRENT_ROLE, CURRENT_COLOR = _resolve_role_on_chain(w3, inst, CURRENT_PRIVATE_KEY)
        print(f"[AUTH] Blockchain resolved role: {CURRENT_ROLE} ({CURRENT_AUTHORITY_NAME})")

        # Investor boot: seed 4 real escrow transactions
        print("[BOOT] Seeding real on-chain transactions for investor dashboard...")
        seed_data = [
            ("0xa1b2c3d4e5f6000000000000000000000000aabb", 150_000.0, "Smart Grid Modernisation Phase 1"),
            ("0xdeadbeef00000000000000000000000000000001", 200_000.0, "Critical Infrastructure Allocation"),
            ("0xc0ffee1234567890abcdef1234567890abcdef12",   5_000.0, "Audit Advisory Retainer"),
            ("0x1111111111111111111111111111111111111111",  85_000.0, "Water Treatment Facility Expansion"),
        ]
        REAL_TRANSACTIONS.clear()
        for raw_addr, amt, purpose in seed_data:
            addr    = w3.to_checksum_address(raw_addr)
            amt_wei = w3.to_wei(amt, "ether")
            r = w3.eth.wait_for_transaction_receipt(
                inst.functions.createEscrow(
                    addr, amt_wei, 0, purpose, False, b"\x00" * 32
                ).transact({"from": coinbase})
            )
            REAL_TRANSACTIONS.insert(0, {
                "hash":    r.transactionHash.hex(),
                "from":    coinbase,
                "to":      addr,
                "amount":  amt,
                "purpose": purpose,
                "block":   r.blockNumber,
                "time":    datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
                "flagged": amt > 100_000,
            })
            print(f"[BOOT]  ✔  {purpose} → Ξ{amt:,.0f}")

        print(f"[WEB3] ✅ FundVault live at: {receipt.contractAddress}")
        return True

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[WEB3] Init failed: {e}")
        return False



def trigger_hardware_scan():
    """Waits for iPhone NFC clipboard tap, resolves authority, updates global state."""
    global CURRENT_PRIVATE_KEY, CURRENT_ROLE, CURRENT_COLOR
    global CURRENT_AUTHORITY_NAME, CURRENT_AUTHORITY_BADGE
    try:
        # nfc_wallet.wait_for_hardware_tap returns (private_key, raw_uid)
        result = nfc_wallet.wait_for_hardware_tap(timeout=30)
        if result:
            # Support both old (key,) and new (key, uid) return signatures
            if isinstance(result, tuple):
                key, raw_uid = result[0], result[1] if len(result) > 1 else ""
            else:
                key, raw_uid = result, ""

            CURRENT_PRIVATE_KEY = key
            if W3_INSTANCE and CONTRACT_INSTANCE:
                CURRENT_ROLE, CURRENT_COLOR = _resolve_role_on_chain(
                    W3_INSTANCE, CONTRACT_INSTANCE, key, raw_uid
                )
            print(f"[NFC] Authenticated: {CURRENT_AUTHORITY_NAME} ({CURRENT_ROLE})")
            return True
    except Exception as e:
        print(f"[NFC] Error: {e}")
    return False


def initiate_transfer(address: str, amount: float, purpose: str, milestone_required: bool = True) -> str:
    """Call the FundVault v2 contract to create a new escrow transfer."""
    if not W3_INSTANCE:
        raise Exception("Blockchain unavailable. Check console for details.")
    try:
        amount_wei = W3_INSTANCE.to_wei(amount, "ether")
        # Use the coinbase (unlocked) account to create the escrow
        coinbase = W3_INSTANCE.eth.accounts[0]
        receipt = W3_INSTANCE.eth.wait_for_transaction_receipt(
            CONTRACT_INSTANCE.functions.createEscrow(
                address, amount_wei, 0, purpose, milestone_required, b"\x00" * 32
            ).transact({"from": coinbase})
        )
        return receipt.transactionHash.hex()
    except Exception as e:
        raise Exception(f"Contract execution failed: {str(e)}")

def generate_kyc_proof(vendor_address: str, gst_number: str) -> bytes:
    """Simulates an external tax database check and generates a cryptographic proof."""
    from config import KYC_ORACLE_PRIVATE_KEY
    from eth_abi.packed import encode_packed
    from eth_utils import keccak
    from eth_account.messages import encode_defunct
    import time
    
    print(f"[API] Querying National Tax DB for GST: {gst_number}...")
    time.sleep(1) # simulate network delay
    print(f"[API] ✅ GST Verified. Tax cleared for 3 years.")
    
    # Generate signature
    data = encode_packed(['address', 'string', 'string'], [vendor_address, gst_number, "TAX_CLEARED"])
    msg_hash = keccak(data)
    msg = encode_defunct(hexstr=msg_hash.hex())
    
    signed = W3_INSTANCE.eth.account.sign_message(msg, private_key=KYC_ORACLE_PRIVATE_KEY)
    return signed.signature


# ────────────────────────────────────────────────────────────
#  COLOUR & STYLE CONSTANTS
# ────────────────────────────────────────────────────────────

C = {
    "BG_DEEP":    "#04040f",
    "BG_CARD":    "#0d0d2b",
    "BG_SIDEBAR": "#070718",
    "BG_INPUT":   "#0a0a20",
    "BORDER":     "#1a1a4e",
    "CYAN":       "#00f5ff",
    "CYAN_DIM":   "#007a80",
    "PURPLE":     "#7b2fff",
    "GREEN":      "#00ff88",
    "RED":        "#ff0033",
    "RED_DIM":    "#800019",
    "AMBER":      "#ffaa00",
    "TEXT":       "#e0e0ff",
    "TEXT_DIM":   "#5a5a8a",
    "TEXT_SIDE":  "#9090b0",
}

LABEL_FONT  = QFont("Segoe UI",  9)
TITLE_FONT  = QFont("Segoe UI", 11, QFont.Bold)
HASH_FONT   = QFont("Consolas",  8)
BIG_FONT    = QFont("Segoe UI", 13, QFont.Bold)
LOGO_FONT   = QFont("Consolas", 14, QFont.Bold)

GLOBAL_STYLESHEET = f"""
    QMainWindow, QWidget {{
        background-color: {C['BG_DEEP']};
        color: {C['TEXT']};
        font-family: "Segoe UI";
    }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{
        background: {C['BG_CARD']};
        width: 6px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {C['CYAN_DIM']};
        border-radius: 3px; min-height: 20px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QLineEdit {{
        background: {C['BG_INPUT']};
        border: 1px solid {C['BORDER']};
        border-radius: 4px;
        color: {C['TEXT']};
        padding: 6px 10px;
        font-family: Consolas; font-size: 9pt;
    }}
    QLineEdit:focus {{
        border: 1px solid {C['CYAN']};
        background: #0a0a28;
    }}
    QTextEdit {{
        background: {C['BG_INPUT']};
        border: 1px solid {C['BORDER']};
        border-radius: 4px;
        color: {C['GREEN']};
        font-family: Consolas; font-size: 8pt;
        padding: 8px;
    }}
    QLabel {{ background: transparent; }}
    QFrame {{ background: transparent; }}
"""


# ────────────────────────────────────────────────────────────
#  WORKER THREADS
# ────────────────────────────────────────────────────────────

class WatchdogWorker(QThread):
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, aes_key=None, parent=None):
        super().__init__(parent)
        self.aes_key = aes_key

    def run(self):
        try:
            from watchdog_daemon import run_watchdog
            result = run_watchdog(aes_key=self.aes_key)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))

class Web3InitWorker(QThread):
    finished = pyqtSignal(bool)
    
    def run(self):
        success = _init_web3()
        self.finished.emit(success)

# ────────────────────────────────────────────────────────────
#  REUSABLE WIDGETS
# ────────────────────────────────────────────────────────────

def _glow_effect(color: str = C["CYAN"], radius: int = 12) -> QGraphicsDropShadowEffect:
    fx = QGraphicsDropShadowEffect()
    fx.setBlurRadius(radius)
    fx.setOffset(0, 0)
    fx.setColor(QColor(color))
    return fx

class NeonButton(QPushButton):
    def __init__(self, text: str, color: str = C["CYAN"], parent=None):
        super().__init__(text, parent)
        self._color = color
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.setMinimumHeight(38)
        self._apply_style(False)
        self.setGraphicsEffect(_glow_effect(color, 8))

    def _apply_style(self, hovered: bool):
        bg = self._color + "33" if hovered else "transparent"
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                border: 1px solid {self._color};
                border-radius: 4px;
                color: {self._color};
                padding: 6px 18px;
                letter-spacing: 1px;
            }}
            QPushButton:disabled {{
                background: #111; border: 1px solid #333; color: #555;
            }}
        """)

    def enterEvent(self, e):
        if self.isEnabled():
            self._apply_style(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.isEnabled():
            self._apply_style(False)
        super().leaveEvent(e)

class SidebarButton(QPushButton):
    def __init__(self, label: str, icon_char: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._icon  = icon_char
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self.setFont(QFont("Segoe UI", 9))
        self.setMinimumHeight(50)
        self._apply_style()
        self.toggled.connect(lambda _: self._apply_style())

    def _apply_style(self):
        if self.isChecked():
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {C['CYAN']}18;
                    border-left: 3px solid {C['CYAN']};
                    border-top: none; border-right: none; border-bottom: none;
                    color: {C['CYAN']};
                    text-align: left;
                    padding-left: 20px;
                    font-weight: bold;
                    font-size: 9pt;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    color: {C['TEXT_SIDE']};
                    text-align: left;
                    padding-left: 23px;
                    font-size: 9pt;
                }}
                QPushButton:hover {{
                    background: {C['CYAN']}0d;
                    color: {C['TEXT']};
                }}
                QPushButton:disabled {{
                    color: #333344;
                }}
            """)

    def setText(self, text):
        super().setText(f"  {self._icon}  {text}")

class Separator(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.HLine)
        self.setStyleSheet(f"color: {C['BORDER']}; background: {C['BORDER']}; max-height: 1px;")
        self.setFixedHeight(1)

class StatusDot(QWidget):
    def __init__(self, color: str = C["GREEN"], size: int = 10, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._alpha = 255
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._pulse)
        self._timer.start(40)
        self._direction = -3

    def _pulse(self):
        self._alpha += self._direction
        if self._alpha <= 80:
            self._direction = 3
        elif self._alpha >= 255:
            self._direction = -3
        self._alpha = max(80, min(255, self._alpha))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self._color)
        c.setAlpha(self._alpha)
        p.setBrush(QBrush(c))
        p.setPen(Qt.NoPen)
        p.drawEllipse(self.rect())


# ────────────────────────────────────────────────────────────
#  TRANSACTION CARD
# ────────────────────────────────────────────────────────────

class TransactionCard(QFrame):
    def __init__(self, tx: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("TxCard")
        flagged = tx["flagged"]
        border_color = C["RED"] if flagged else C["BORDER"]
        badge_bg     = C["RED"]   if flagged else C["CYAN"] + "33"
        badge_color  = C["RED"]   if flagged else C["GREEN"]
        badge_text   = "⚠  FLAGGED" if flagged else "✔  VERIFIED"

        self.setStyleSheet(f"""
            #TxCard {{
                background: {C['BG_CARD']};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)
        self.setContentsMargins(0, 0, 0, 0)

        if flagged:
            self.setGraphicsEffect(_glow_effect(C["RED"], 14))

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(6)

        row1 = QHBoxLayout()
        hash_lbl = QLabel(f"TX  {tx['hash'][:18]}…{tx['hash'][-6:]}")
        hash_lbl.setFont(HASH_FONT)
        hash_lbl.setStyleSheet(f"color: {C['GREEN']};")

        badge = QLabel(badge_text)
        badge.setFont(QFont("Segoe UI", 8, QFont.Bold))
        badge.setStyleSheet(f"""
            background: {badge_bg}; color: {badge_color};
            border: 1px solid {badge_color};
            border-radius: 3px; padding: 1px 8px;
        """)
        badge.setAlignment(Qt.AlignCenter)
        row1.addWidget(hash_lbl)
        row1.addStretch()
        row1.addWidget(badge)
        root.addLayout(row1)

        addr_row = QHBoxLayout()
        addr_row.setSpacing(6)

        def _addr_chip(label_text, addr):
            chip = QFrame()
            chip.setStyleSheet(f"""
                background: {C['BG_INPUT']}; border: 1px solid {C['BORDER']};
                border-radius: 4px;
            """)
            lay = QHBoxLayout(chip)
            lay.setContentsMargins(6, 3, 6, 3)
            lay.setSpacing(5)
            role_lbl = QLabel(label_text)
            role_lbl.setFont(QFont("Segoe UI", 7, QFont.Bold))
            role_lbl.setStyleSheet(f"color: {C['TEXT_DIM']}; background: transparent;")
            addr_text = QLabel(f"{addr[:8]}…{addr[-6:]}")
            addr_text.setFont(QFont("Consolas", 8))
            addr_text.setStyleSheet(f"color: {C['TEXT']}; background: transparent;")
            lay.addWidget(role_lbl)
            lay.addWidget(addr_text)
            return chip

        addr_row.addWidget(_addr_chip("FROM", tx["from"]))
        arrow = QLabel("→")
        arrow.setFont(QFont("Segoe UI", 11, QFont.Bold))
        arrow.setStyleSheet(f"color: {C['CYAN']}; background: transparent;")
        addr_row.addWidget(arrow)
        addr_row.addWidget(_addr_chip("TO", tx["to"]))
        addr_row.addStretch()
        root.addLayout(addr_row)

        row3 = QHBoxLayout()
        amt_lbl = QLabel(f"Ξ {tx['amount']:,.2f}")
        amt_lbl.setFont(QFont("Consolas", 10, QFont.Bold))
        amt_lbl.setStyleSheet(f"color: {C['CYAN']};")

        purpose_lbl = QLabel(tx["purpose"])
        purpose_lbl.setFont(LABEL_FONT)
        purpose_lbl.setStyleSheet(f"color: {C['TEXT_DIM']};")

        time_lbl = QLabel(tx["time"])
        time_lbl.setFont(QFont("Consolas", 8))
        time_lbl.setStyleSheet(f"color: {C['TEXT_DIM']};")

        row3.addWidget(amt_lbl)
        row3.addWidget(purpose_lbl)
        row3.addStretch()
        row3.addWidget(time_lbl)
        root.addLayout(row3)


# ────────────────────────────────────────────────────────────
#  PANELS
# ────────────────────────────────────────────────────────────

class PublicFeedPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_stats)
        self._refresh_timer.start(5000)

    def _refresh_stats(self):
        def _fetch():
            try:
                if W3_INSTANCE and CONTRACT_INSTANCE:
                    bal_wei = W3_INSTANCE.eth.get_balance(CONTRACT_INSTANCE.address)
                    bal_eth = W3_INSTANCE.from_wei(bal_wei, "ether")
                    escrow_count = CONTRACT_INSTANCE.functions.escrowCounter().call()
                    QTimer.singleShot(0, lambda: self._update_stats(float(bal_eth), escrow_count))
            except Exception:
                pass
        threading.Thread(target=_fetch, daemon=True).start()

    def _update_stats(self, balance_eth: float, escrow_count: int):
        self._treasury_lbl.setText(f"Ξ {balance_eth:,.2f} ETH")
        self._escrow_lbl.setText(f"{escrow_count} Escrows")
        self._chain_lbl.setText("● LIVE ON-CHAIN")

    def populate_transactions(self):
        for i in reversed(range(self._card_layout.count() - 1)): 
            self._card_layout.itemAt(i).widget().setParent(None)
        
        self.count_lbl.setText(f"{len(REAL_TRANSACTIONS)} transactions  •  Live")
        for tx in REAL_TRANSACTIONS:
            self._card_layout.insertWidget(self._card_layout.count() - 1, TransactionCard(tx))

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        title = QLabel("◈  PUBLIC LEDGER FEED")
        title.setFont(BIG_FONT)
        title.setStyleSheet(f"color: {C['CYAN']};")
        title.setGraphicsEffect(_glow_effect(C["CYAN"], 10))

        self.count_lbl = QLabel(f"0 transactions  •  Live")
        self.count_lbl.setFont(QFont("Segoe UI", 9))
        self.count_lbl.setStyleSheet(f"color: {C['TEXT_DIM']};")
        hdr.addWidget(title)
        hdr.addStretch()

        stats_frame = QFrame()
        stats_frame.setObjectName("StatsFrame")
        stats_frame.setStyleSheet(f"""
            #StatsFrame {{
                background: {C['BG_CARD']};
                border: 1px solid {C['CYAN']}44;
                border-radius: 8px;
            }}
        """)
        stats_lay = QHBoxLayout(stats_frame)
        stats_lay.setContentsMargins(20, 14, 20, 14)
        stats_lay.setSpacing(0)

        def _stat_col(label_text, value_text, color):
            col = QVBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFont(QFont("Segoe UI", 8))
            lbl.setStyleSheet(f"color: {C['TEXT_DIM']};")
            val = QLabel(value_text)
            val.setFont(QFont("Consolas", 14, QFont.Bold))
            val.setStyleSheet(f"color: {color};")
            col.addWidget(lbl)
            col.addWidget(val)
            return col, val

        col1, self._treasury_lbl = _stat_col("TREASURY BALANCE", "Ξ Loading…", C["CYAN"])
        col2, self._escrow_lbl   = _stat_col("ACTIVE ESCROWS",   "Loading…",  C["PURPLE"])
        col3, self._chain_lbl    = _stat_col("LEDGER STATUS",    "● SYNCING", C["GREEN"])

        divider_style = f"background: {C['BORDER']}; max-width: 1px; min-width:1px;"
        div1 = QFrame(); div1.setStyleSheet(divider_style)
        div2 = QFrame(); div2.setStyleSheet(divider_style)

        stats_lay.addLayout(col1)
        stats_lay.addSpacing(24)
        stats_lay.addWidget(div1)
        stats_lay.addSpacing(24)
        stats_lay.addLayout(col2)
        stats_lay.addSpacing(24)
        stats_lay.addWidget(div2)
        stats_lay.addSpacing(24)
        stats_lay.addLayout(col3)
        stats_lay.addStretch()

        public_note = QLabel("🌐  This ledger is publicly verifiable. No login required.")
        public_note.setFont(QFont("Segoe UI", 8))
        public_note.setStyleSheet(f"color: {C['GREEN']}; font-style: italic;")

        hdr.addWidget(self.count_lbl)
        dot = StatusDot(C["GREEN"])
        hdr.addWidget(dot)

        # RTI Export button
        self.rti_btn = NeonButton("  📄  EXPORT RTI REPORT", C["AMBER"])
        self.rti_btn.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.rti_btn.setFixedHeight(32)
        self.rti_btn.clicked.connect(self._on_export_rti)
        hdr.addSpacing(8)
        hdr.addWidget(self.rti_btn)

        root.addLayout(hdr)
        root.addWidget(stats_frame)
        root.addWidget(public_note)
        root.addWidget(Separator())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        self._card_layout = QVBoxLayout(container)
        self._card_layout.setContentsMargins(0, 4, 0, 4)
        self._card_layout.setSpacing(8)
        self._card_layout.addStretch()
        
        scroll.setWidget(container)
        root.addWidget(scroll)

    def prepend_transaction(self, tx: dict):
        card = TransactionCard(tx)
        self._card_layout.insertWidget(0, card)
        self.count_lbl.setText(f"{len(REAL_TRANSACTIONS)} transactions  •  Live")

    def _on_export_rti(self):
        self.rti_btn.setEnabled(False)
        self.rti_btn.setText("  ⏳  GENERATING…")
        def _do():
            try:
                import sys, os
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
                from rti_report import generate_rti_pdf
                path = generate_rti_pdf(REAL_TRANSACTIONS)
                import subprocess
                subprocess.Popen(["open", path])  # macOS: open in browser/Preview
                QTimer.singleShot(0, lambda: self.rti_btn.setText("  ✔  REPORT OPENED"))
            except Exception as exc:
                print(f"[RTI] Error: {exc}")
                QTimer.singleShot(0, lambda: self.rti_btn.setText("  ✘  FAILED"))
            QTimer.singleShot(3000, lambda: self.rti_btn.setText("  📄  EXPORT RTI REPORT"))
            QTimer.singleShot(3000, lambda: self.rti_btn.setEnabled(True))
        threading.Thread(target=_do, daemon=True).start()


class AdminPanel(QWidget):
    transfer_submitted = pyqtSignal(str, float, str)
    auth_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        title = QLabel("⬡  ADMIN — INITIATE TRANSFER")
        title.setFont(BIG_FONT)
        title.setStyleSheet(f"color: {C['CYAN']};")
        title.setGraphicsEffect(_glow_effect(C["CYAN"], 10))
        root.addWidget(title)
        root.addWidget(Separator())

        role_row = QHBoxLayout()
        role_badge = QLabel("  ⬡  ROLE : ADMIN  ")
        role_badge.setFont(QFont("Consolas", 9, QFont.Bold))
        role_badge.setStyleSheet(f"""
            background: {C['PURPLE']}33; border: 1px solid {C['PURPLE']};
            border-radius: 4px; color: {C['PURPLE']}; padding: 3px 10px;
        """)
        role_row.addWidget(role_badge)
        
        self.reauth_btn = NeonButton("◈ RE-AUTHENTICATE VIA IPHONE", C["PURPLE"])
        self.reauth_btn.clicked.connect(self._on_nfc)
        role_row.addStretch()
        role_row.addWidget(self.reauth_btn)
        root.addLayout(role_row)

        form_frame = QFrame()
        form_frame.setObjectName("FormCard")
        form_frame.setStyleSheet(f"""
            #FormCard {{
                background: {C['BG_CARD']}; border: 1px solid {C['BORDER']};
                border-radius: 8px;
            }}
        """)
        form_layout = QFormLayout(form_frame)
        form_layout.setContentsMargins(24, 24, 24, 24)
        form_layout.setSpacing(14)
        form_layout.setLabelAlignment(Qt.AlignRight)

        # ── Vendor Registration (ZK-KYC) ──
        vendor_frame = QFrame()
        vendor_frame.setObjectName("VendorFrame")
        vendor_frame.setStyleSheet(f"""
            #VendorFrame {{
                background: {C['BG_CARD']}; border: 1px solid {C['GREEN']}44; border-radius: 8px;
            }}
        """)
        v_layout = QFormLayout(vendor_frame)
        v_layout.setContentsMargins(24, 16, 24, 16)
        v_layout.setSpacing(14)
        v_layout.setLabelAlignment(Qt.AlignRight)

        def _lbl(text):
            l = QLabel(text)
            l.setFont(QFont("Segoe UI", 9))
            l.setStyleSheet(f"color: {C['TEXT_DIM']};")
            return l

        self.v_addr = QLineEdit()
        self.v_addr.setPlaceholderText("0xVendor...")
        self.v_name = QLineEdit()
        self.v_name.setPlaceholderText("Company Name")
        self.v_gst  = QLineEdit()
        self.v_gst.setPlaceholderText("GST Number")
        
        v_title = QLabel("ZK-KYC VENDOR REGISTRATION")
        v_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        v_title.setStyleSheet(f"color: {C['GREEN']};")
        
        self.v_btn = NeonButton("  ⬡  VERIFY TAX DB & REGISTER", C["GREEN"])
        self.v_btn.clicked.connect(self._on_vendor_register)
        
        v_layout.addRow(v_title)
        v_layout.addRow(_lbl("Address"), self.v_addr)
        v_layout.addRow(_lbl("Name"), self.v_name)
        v_layout.addRow(_lbl("GST No"), self.v_gst)
        v_layout.addRow("", self.v_btn)
        
        root.addWidget(vendor_frame)


        form_frame = QFrame()
        form_frame.setObjectName("FormCard")
        form_frame.setStyleSheet(f"""
            #FormCard {{
                background: {C['BG_CARD']}; border: 1px solid {C['BORDER']};
                border-radius: 8px;
            }}
        """)
        form_layout = QFormLayout(form_frame)
        form_layout.setContentsMargins(24, 24, 24, 24)
        form_layout.setSpacing(14)
        form_layout.setLabelAlignment(Qt.AlignRight)

        self.addr_input = QLineEdit()
        self.addr_input.setPlaceholderText("0xContractorAddress…")
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("e.g. 50000.00")
        self.purpose_input = QLineEdit()
        self.purpose_input.setPlaceholderText("e.g. Road Construction Phase 2")

        from PyQt5.QtWidgets import QCheckBox
        self.milestone_chk = QCheckBox("Require milestone document before release")
        self.milestone_chk.setStyleSheet(f"color: {C['AMBER']}; font-size: 9pt;")
        self.milestone_chk.setChecked(True)

        form_layout.addRow(_lbl("Contractor Address"), self.addr_input)
        form_layout.addRow(_lbl("Amount (ETH)"),       self.amount_input)
        form_layout.addRow(_lbl("Purpose"),            self.purpose_input)
        form_layout.addRow(_lbl("Milestone Gate"),     self.milestone_chk)
        root.addWidget(form_frame)

        # Multi-sig approve section
        approve_frame = QFrame()
        approve_frame.setObjectName("ApproveFrame")
        approve_frame.setStyleSheet(f"""
            #ApproveFrame {{
                background: {C['BG_CARD']}; border: 1px solid {C['PURPLE']}44; border-radius: 8px;
            }}
        """)
        approve_lay = QHBoxLayout(approve_frame)
        approve_lay.setContentsMargins(16, 12, 16, 12)
        approve_lay.setSpacing(14)

        approve_lbl_col = QVBoxLayout()
        approve_title = QLabel("MULTI-SIGNATURE APPROVAL")
        approve_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        approve_title.setStyleSheet(f"color: {C['PURPLE']};")
        approve_sub = QLabel("Cast your hardware-key approval for the latest pending escrow.\nFunds release only when N-of-M signers approve.")
        approve_sub.setFont(QFont("Segoe UI", 8))
        approve_sub.setStyleSheet(f"color: {C['TEXT_DIM']};")
        approve_sub.setWordWrap(True)
        approve_lbl_col.addWidget(approve_title)
        approve_lbl_col.addWidget(approve_sub)
        approve_lay.addLayout(approve_lbl_col)
        approve_lay.addStretch()

        self.approve_btn = NeonButton("  ⬡  APPROVE RELEASE", C["PURPLE"])
        self.approve_btn.clicked.connect(self._on_approve_release)
        self.approve_status = QLabel("")
        self.approve_status.setFont(QFont("Consolas", 8))
        self.approve_status.setStyleSheet(f"color: {C['TEXT_DIM']};")
        approve_lay.addWidget(self.approve_btn)

        approve_lbl_col.addWidget(self.approve_status)
        root.addWidget(approve_frame)

        nfc_note = QLabel("⬡  NFC hardware wallet tap required to authorise transfer.")
        nfc_note.setFont(QFont("Segoe UI", 8))
        nfc_note.setStyleSheet(f"color: {C['TEXT_DIM']}; font-style: italic;")
        root.addWidget(nfc_note)

        btn_row = QHBoxLayout()
        self.send_btn = NeonButton("  ▶  SEND FUNDS", C["CYAN"])
        self.send_btn.setMinimumWidth(200)
        self.send_btn.clicked.connect(self._on_send)
        btn_row.addWidget(self.send_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._toast = QLabel("")
        self._toast.setFont(QFont("Consolas", 9))
        self._toast.setAlignment(Qt.AlignLeft)
        root.addWidget(self._toast)
        root.addStretch()

    def _on_vendor_register(self):
        v_addr = self.v_addr.text().strip()
        v_name = self.v_name.text().strip()
        v_gst = self.v_gst.text().strip()
        
        if not v_addr or not v_name or not v_gst:
            self._show_toast("⚠ Fill all vendor details", C["RED"])
            return
            
        def _task():
            try:
                proof = generate_kyc_proof(v_addr, v_gst)
                coinbase = W3_INSTANCE.eth.accounts[0] # assuming coinbase is the contract owner
                W3_INSTANCE.eth.wait_for_transaction_receipt(
                    CONTRACT_INSTANCE.functions.registerVendor(
                        W3_INSTANCE.to_checksum_address(v_addr), 
                        v_name, 
                        v_gst, 
                        proof
                    ).transact({"from": coinbase})
                )
                QTimer.singleShot(0, lambda: self._show_toast("✔ Vendor Registered via ZK-KYC Oracle", C["GREEN"]))
                QTimer.singleShot(0, lambda: self.v_addr.clear())
                QTimer.singleShot(0, lambda: self.v_name.clear())
                QTimer.singleShot(0, lambda: self.v_gst.clear())
            except Exception as e:
                QTimer.singleShot(0, lambda: self._show_toast(f"✘ KYC Failed: {e}", C["RED"]))
                
        self.v_btn.setEnabled(False)
        self.v_btn.setText("  ⏳  QUERYING TAX DB...")
        
        def _done():
            self.v_btn.setEnabled(True)
            self.v_btn.setText("  ⬡  VERIFY TAX DB & REGISTER")
            
        t = threading.Thread(target=lambda: [_task(), QTimer.singleShot(0, _done)], daemon=True)
        t.start()

    def _on_send(self):
        addr    = self.addr_input.text().strip()
        purpose = self.purpose_input.text().strip()
        try:
            amount = float(self.amount_input.text().strip())
        except ValueError:
            self._show_toast("⚠  Invalid amount — enter a number.", C["RED"])
            return

        if not addr or not purpose:
            self._show_toast("⚠  Fill all fields.", C["RED"])
            return
        if not CURRENT_PRIVATE_KEY:
            self._show_toast("⚠  Tap NFC tag first to authorise transfer.", C["RED"])
            return

        self.send_btn.setEnabled(False)
        self._show_toast("⏳  Writing escrow to blockchain…", C["AMBER"])
        milestone_req = self.milestone_chk.isChecked()

        def _do():
            try:
                tx = initiate_transfer(addr, amount, purpose, milestone_required=milestone_req)
                self.transfer_submitted.emit(addr, amount, purpose)
                QTimer.singleShot(0, lambda: self._show_toast(f"✔  On-chain! TX: {tx[:18]}…", C["GREEN"]))
                QTimer.singleShot(0, lambda: self.approve_status.setText(f"Escrow created. Cast your approval ▶"))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._show_toast(f"✘  {exc}", C["RED"]))
            finally:
                QTimer.singleShot(0, lambda: self.send_btn.setEnabled(True))
                QTimer.singleShot(0, self.addr_input.clear)
                QTimer.singleShot(0, self.amount_input.clear)
                QTimer.singleShot(0, self.purpose_input.clear)

        threading.Thread(target=_do, daemon=True).start()

    def _on_approve_release(self):
        if not CURRENT_PRIVATE_KEY:
            self._show_toast("⚠  Tap NFC tag first.", C["RED"])
            return
        self.approve_btn.setEnabled(False)
        self._show_toast("⏳  Submitting multi-sig approval to blockchain…", C["PURPLE"])

        def _do():
            try:
                if not CONTRACT_INSTANCE or not W3_INSTANCE:
                    raise Exception("Blockchain not ready")
                escrow_id   = CONTRACT_INSTANCE.functions.escrowCounter().call() - 1
                signer_addr = W3_INSTANCE.eth.account.from_key(CURRENT_PRIVATE_KEY).address
                CONTRACT_INSTANCE.functions.approveRelease(escrow_id).transact({"from": signer_addr})
                count, milestone_ok = CONTRACT_INSTANCE.functions.getEscrowApprovals(escrow_id).call()
                required = CONTRACT_INSTANCE.functions.requiredApprovals().call()
                status_msg = f"✔  Approval {count}/{required} cast for escrow #{escrow_id}"
                if not milestone_ok:
                    status_msg += " — awaiting Auditor milestone"
                QTimer.singleShot(0, lambda: self._show_toast(status_msg, C["GREEN"]))
                QTimer.singleShot(0, lambda: self.approve_status.setText(status_msg))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._show_toast(f"✘  {exc}", C["RED"]))
            QTimer.singleShot(0, lambda: self.approve_btn.setEnabled(True))

        threading.Thread(target=_do, daemon=True).start()

    def _on_nfc(self):
        self.reauth_btn.setEnabled(False)
        self._show_toast("◈  Use iOS Shortcut to copy NFC string to Universal Clipboard now… (30s)", C["PURPLE"])

        def _scan():
            ok = trigger_hardware_scan()
            if ok:
                QTimer.singleShot(0, lambda: self._show_toast("✔  iPhone NFC Authenticated! Role permissions updated.", C["GREEN"]))
                self.auth_requested.emit()
            else:
                QTimer.singleShot(0, lambda: self._show_toast("✘  NFC timeout — no clipboard sync detected.", C["RED"]))
            QTimer.singleShot(0, lambda: self.reauth_btn.setEnabled(True))

        threading.Thread(target=_scan, daemon=True).start()

    def _show_toast(self, msg: str, color: str):
        self._toast.setText(msg)
        self._toast.setStyleSheet(f"color: {color};")
        QTimer.singleShot(6000, lambda: self._toast.setText(""))


class AuditorPanel(QWidget):
    watchdog_triggered = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_cid      = None
        self._current_filepath = None
        self._alert_active     = False
        self._worker           = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("⬡  AUDITOR PANEL")
        title.setFont(BIG_FONT)
        title.setStyleSheet(f"color: {C['CYAN']};")
        title.setGraphicsEffect(_glow_effect(C["CYAN"], 10))
        root.addWidget(title)
        root.addWidget(Separator())

        self.alert_banner = QFrame()
        self.alert_banner.setObjectName("AlertBanner")
        self._set_banner_normal()

        banner_layout = QVBoxLayout(self.alert_banner)
        banner_layout.setContentsMargins(20, 16, 20, 16)
        banner_layout.setSpacing(6)

        self.alert_icon  = QLabel("✔  ALL SYSTEMS NORMAL")
        self.alert_icon.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.alert_icon.setAlignment(Qt.AlignCenter)

        self.alert_sub   = QLabel("No suspicious transactions detected.")
        self.alert_sub.setFont(QFont("Segoe UI", 9))
        self.alert_sub.setAlignment(Qt.AlignCenter)
        self.alert_sub.setStyleSheet(f"color: {C['TEXT_DIM']};")

        banner_layout.addWidget(self.alert_icon)
        banner_layout.addWidget(self.alert_sub)
        root.addWidget(self.alert_banner)

        self.detail_card = QFrame()
        self.detail_card.setObjectName("DetailCard")
        self.detail_card.setStyleSheet(f"""
            #DetailCard {{
                background: {C['BG_CARD']}; border: 1px solid {C['RED_DIM']}; border-radius: 6px;
            }}
        """)
        self.detail_card.hide()

        dc_layout = QVBoxLayout(self.detail_card)
        dc_layout.setContentsMargins(16, 12, 16, 12)
        dc_layout.setSpacing(4)

        self.dc_hash   = QLabel()
        self.dc_hash.setFont(HASH_FONT)
        self.dc_hash.setStyleSheet(f"color: {C['GREEN']};")
        self.dc_amount = QLabel()
        self.dc_amount.setFont(QFont("Consolas", 10, QFont.Bold))
        self.dc_amount.setStyleSheet(f"color: {C['RED']};")
        self.dc_flags  = QLabel()
        self.dc_flags.setFont(QFont("Segoe UI", 9))
        self.dc_flags.setStyleSheet(f"color: {C['AMBER']};")
        self.dc_flags.setWordWrap(True)
        self.dc_cid    = QLabel()
        self.dc_cid.setFont(QFont("Consolas", 8))
        self.dc_cid.setStyleSheet(f"color: {C['TEXT_DIM']};")
        self.dc_cid.setWordWrap(True)

        dc_layout.addWidget(self.dc_hash)
        dc_layout.addWidget(self.dc_amount)
        dc_layout.addWidget(self.dc_flags)
        dc_layout.addWidget(self.dc_cid)
        root.addWidget(self.detail_card)

        btn_row = QHBoxLayout()
        self.decrypt_btn = NeonButton("  ⬡  READ AUDIT REPORT", C["CYAN"])
        self.decrypt_btn.setEnabled(False)
        self.decrypt_btn.clicked.connect(self._on_decrypt)

        self.watchdog_btn = NeonButton("  ▶  TRIGGER WATCHDOG TEST", C["PURPLE"])
        self.watchdog_btn.clicked.connect(self._on_trigger_watchdog)

        btn_row.addWidget(self.decrypt_btn)
        btn_row.addWidget(self.watchdog_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── Human-readable audit card (shown after decrypt) ──
        self.audit_card = QFrame()
        self.audit_card.setObjectName("AuditCard")
        self.audit_card.setStyleSheet(f"""
            #AuditCard {{
                background: {C['BG_CARD']};
                border: 1px solid {C['AMBER']}55;
                border-radius: 8px;
            }}
        """)
        self.audit_card.hide()

        ac_layout = QVBoxLayout(self.audit_card)
        ac_layout.setContentsMargins(20, 16, 20, 16)
        ac_layout.setSpacing(10)

        # Header row
        ac_hdr = QHBoxLayout()
        self.ac_title = QLabel("AUDIT REPORT")
        self.ac_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.ac_title.setStyleSheet(f"color: {C['AMBER']};")
        self.ac_severity = QLabel()
        self.ac_severity.setFont(QFont("Consolas", 9, QFont.Bold))
        ac_hdr.addWidget(self.ac_title)
        ac_hdr.addStretch()
        ac_hdr.addWidget(self.ac_severity)
        ac_layout.addLayout(ac_hdr)

        ac_layout.addWidget(Separator())

        # Summary text (plain English)
        self.ac_summary = QLabel()
        self.ac_summary.setFont(QFont("Segoe UI", 10))
        self.ac_summary.setStyleSheet(f"color: {C['TEXT']};")
        self.ac_summary.setWordWrap(True)
        ac_layout.addWidget(self.ac_summary)

        # Flags row
        self.ac_flags_lbl = QLabel()
        self.ac_flags_lbl.setFont(QFont("Segoe UI", 9))
        self.ac_flags_lbl.setStyleSheet(f"color: {C['AMBER']};")
        self.ac_flags_lbl.setWordWrap(True)
        ac_layout.addWidget(self.ac_flags_lbl)

        # IPFS pin row
        self.ac_ipfs_lbl = QLabel()
        self.ac_ipfs_lbl.setFont(QFont("Consolas", 8))
        self.ac_ipfs_lbl.setStyleSheet(f"color: {C['TEXT_DIM']};")
        self.ac_ipfs_lbl.setWordWrap(True)
        ac_layout.addWidget(self.ac_ipfs_lbl)

        ac_layout.addWidget(Separator())

        # ── Action buttons ──
        action_lbl = QLabel("AUDITOR ACTIONS")
        action_lbl.setFont(QFont("Segoe UI", 8))
        action_lbl.setStyleSheet(f"color: {C['TEXT_DIM']}; letter-spacing: 1px;")
        ac_layout.addWidget(action_lbl)

        action_row = QHBoxLayout()
        self.freeze_btn = NeonButton("  🔒  FREEZE TRANSACTION", C["RED"])
        self.freeze_btn.setToolTip("Freezes the flagged escrow on-chain, blocking release of funds.")
        self.freeze_btn.clicked.connect(self._on_freeze)

        self.cancel_btn = NeonButton("  ✕  VOTE TO CANCEL", C["AMBER"])
        self.cancel_btn.setToolTip("Casts your auditor vote to permanently cancel and refund this escrow.")
        self.cancel_btn.clicked.connect(self._on_vote_cancel)

        self.mark_safe_btn = NeonButton("  ✔  MARK AS SAFE", C["GREEN"])
        self.mark_safe_btn.setToolTip("Clears the alert — transaction has been reviewed and is legitimate.")
        self.mark_safe_btn.clicked.connect(self._on_mark_safe)

        action_row.addWidget(self.freeze_btn)
        action_row.addWidget(self.cancel_btn)
        action_row.addWidget(self.mark_safe_btn)
        action_row.addStretch()
        ac_layout.addLayout(action_row)

        root.addWidget(self.audit_card)

        # Milestone submission section
        self._build_milestone_section(root)

        self._status = QLabel("")
        self._status.setFont(QFont("Consolas", 8))
        self._status.setStyleSheet(f"color: {C['TEXT_DIM']};")
        root.addWidget(self._status)

    def _set_banner_normal(self):
        self.alert_banner.setStyleSheet(f"#AlertBanner {{ background: {C['GREEN']}11; border: 1px solid {C['GREEN']}44; border-radius: 8px; }}")
        if hasattr(self, "alert_icon"):
            self.alert_icon.setText("✔  ALL SYSTEMS NORMAL")
            self.alert_icon.setStyleSheet(f"color: {C['GREEN']};")
            self.alert_sub.setText("No suspicious transactions detected.")

    def _set_banner_alert(self):
        self.alert_banner.setStyleSheet(f"#AlertBanner {{ background: {C['RED']}22; border: 2px solid {C['RED']}; border-radius: 8px; }}")
        self.alert_banner.setGraphicsEffect(_glow_effect(C["RED"], 20))
        self.alert_icon.setText("⚠   SUSPICIOUS TRANSACTION FLAGGED")
        self.alert_icon.setStyleSheet(f"color: {C['RED']};")
        self.alert_sub.setText("Automated watchdog detected anomalous activity. IPFS audit report has been generated and pinned.")
        self.alert_sub.setStyleSheet(f"color: {C['AMBER']};")

    def raise_alert(self, result: dict):
        self._alert_active     = True
        self._current_cid      = result.get("cid")
        self._current_filepath = result.get("filepath")
        report = result.get("report", {})
        tx     = report.get("transaction", {})

        self._set_banner_alert()
        self.detail_card.show()
        self.dc_hash.setText(f"TX  {tx.get('hash','N/A')[:22]}…")
        self.dc_amount.setText(f"Ξ {tx.get('amount_eth', 0):,.2f}  —  CRITICAL")
        self.dc_flags.setText(f"FLAGS:  {'  |  '.join(report.get('flags', []))}")
        self.dc_cid.setText(f"IPFS CID:  {self._current_cid or 'Uploading…'}")

        self.decrypt_btn.setEnabled(True)
        self.decrypt_btn.setGraphicsEffect(_glow_effect(C["CYAN"], 18))

    def clear_alert(self):
        self._alert_active = False
        self._current_cid  = None
        self._set_banner_normal()
        self.detail_card.hide()
        self.audit_card.hide()
        self.alert_banner.setGraphicsEffect(None)
        self.decrypt_btn.setEnabled(False)

    def _on_decrypt(self):
        from pathlib import Path
        target = Path(self._current_filepath) if self._current_filepath and Path(self._current_filepath).exists() else None
        if not target:
            for search in [os.path.join(os.path.dirname(__file__), '..', 'core', 'reports'), "reports"]:
                d = Path(search)
                if d.exists():
                    files = sorted(d.glob("*.json"), reverse=True)
                    if files:
                        target = files[0]
                        break
        if not target:
            self._status.setText("No report found. Click TRIGGER WATCHDOG first.")
            return

        data = json.loads(target.read_text(encoding="utf-8"))
        if data.get("locked"):
            if CURRENT_ROLE != "AUDITOR":
                self._status.setText("⚠  HARDWARE KEY REQUIRED — Tap Auditor NFC tag first.")
                self._render_locked_card()
                return
            try:
                from watchdog_daemon import decrypt_report
                decrypted = json.loads(decrypt_report(data["encrypted_payload"], CURRENT_PRIVATE_KEY))
                self._render_report_card(decrypted)
                self._status.setText(f"✔  Decrypted with NFC hardware key — {target.name}")
            except Exception as e:
                self._status.setText(f"✘  Decryption failed: {e}")
        else:
            self._render_report_card(data)
            self._status.setText(f"✔  Audit report loaded — {target.name}")

    def _render_locked_card(self):
        self.audit_card.show()
        self.ac_title.setText("REPORT LOCKED")
        self.ac_severity.setText("  🔒 ENCRYPTED  ")
        self.ac_severity.setStyleSheet(f"background: {C['TEXT_DIM']}22; border: 1px solid {C['TEXT_DIM']}; border-radius: 3px; color: {C['TEXT_DIM']}; padding: 2px 8px;")
        self.ac_summary.setText(
            "This audit report is protected by AES-256-GCM encryption.\n"
            "To read its contents, the physical Auditor NFC hardware tag must be\n"
            "tapped on the iPhone and authenticated via Universal Clipboard."
        )
        self.ac_flags_lbl.setText("")
        self.ac_ipfs_lbl.setText("")
        self.freeze_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.mark_safe_btn.setEnabled(False)

    def _render_report_card(self, report: dict):
        """Display the audit report in plain, human-readable English."""
        self._last_report = report
        tx        = report.get("transaction", {})
        flags     = report.get("flags", [])
        severity  = report.get("severity", "UNKNOWN")
        amount    = tx.get("amount_eth", 0)
        tx_hash   = tx.get("hash", "N/A")
        from_addr = tx.get("from", "Unknown")
        to_addr   = tx.get("to", "Unknown")
        block     = tx.get("block", "?")
        generated = report.get("generated_at", "N/A")
        cid       = self._current_cid or "Not pinned"

        # Severity chip colour
        sev_color = {"CRITICAL": C["RED"], "HIGH": C["AMBER"], "MEDIUM": C["CYAN"]}.get(severity, C["TEXT_DIM"])
        self.ac_severity.setText(f"  {severity}  ")
        self.ac_severity.setStyleSheet(
            f"background: {sev_color}22; border: 1px solid {sev_color}; "
            f"border-radius: 3px; color: {sev_color}; padding: 2px 8px;"
        )

        # Plain-English summary
        flag_descriptions = {
            "AMOUNT_EXCEEDS_THRESHOLD":  "the transfer amount exceeds the authorised threshold",
            "UNVERIFIED_CONTRACTOR":     "the recipient address is on the unverified contractor watchlist",
            "RAPID_SUCCESSION_TX":       "multiple transactions were submitted in rapid succession",
            "MISSING_PURPOSE_FIELD":     "no payment purpose was declared for this transfer",
            "GENERIC_ANOMALY":           "an unclassified anomaly was detected in the transaction pattern",
        }
        reasons = "; ".join(flag_descriptions.get(f, f.lower().replace("_", " ")) for f in flags)

        # Extract AI Insights if present
        ai_insights = report.get("ai_insights", {})
        ai_text = ""
        if ai_insights:
            knn_dist = ai_insights.get("knn_distance", 0)
            conf = ai_insights.get("confidence_score", 0)
            semantic = ai_insights.get("semantic_analysis", "")
            if ai_insights.get("is_anomaly") or semantic:
                ai_text = (
                    f"🤖 AI ENSEMBLE ANALYSIS:\n"
                    f"• KNN Anomaly Distance: {knn_dist} (Confidence: {conf}%)\n"
                    f"• Semantic Evaluation: {semantic}\n\n"
                )

        summary = (
            f"The Ledger Nexus Watchdog has flagged a transfer of "
            f"Ξ {amount:,.2f} ETH originating from address "
            f"{from_addr[:16]}… directed to {to_addr[:16]}… "
            f"at block #{block}.\n\n"
            f"Rule-based triggers: {reasons}.\n\n"
            f"{ai_text}"
            f"As the authorised Auditor, you must review and take action below."
        )
        self.ac_summary.setText(summary)

        # Flags in readable pill format
        flag_pills = "   ".join(f"▸ {f.replace('_', ' ')}" for f in flags)
        if ai_insights.get("is_anomaly"):
            flag_pills += "   ▸ AI_MATHEMATICAL_ANOMALY"
        self.ac_flags_lbl.setText(f"Violation triggers:  {flag_pills}")

        # IPFS traceability
        self.ac_ipfs_lbl.setText(
            f"Tamper-proof record pinned to IPFS\n"
            f"CID: {cid}\n"
            f"Generated: {generated}"
        )

        self.audit_card.show()
        self.freeze_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.mark_safe_btn.setEnabled(True)

    def _on_freeze(self):
        """Call freezeTransaction on the smart contract for the flagged escrow."""
        self._action_toast("🔒  Freeze request submitted to blockchain…", C["RED"])
        self.freeze_btn.setEnabled(False)
        def _do():
            try:
                if CONTRACT_INSTANCE and W3_INSTANCE:
                    # Escrow ID is the latest one created
                    escrow_id = CONTRACT_INSTANCE.functions.escrowCounter().call() - 1
                    auditor_addr = W3_INSTANCE.eth.account.from_key(CURRENT_PRIVATE_KEY).address
                    CONTRACT_INSTANCE.functions.freezeTransaction(escrow_id).transact({"from": auditor_addr})
                    QTimer.singleShot(0, lambda: self._action_toast(
                        f"✔  Escrow #{escrow_id} FROZEN on-chain. Funds are locked pending review.", C["RED"]))
                else:
                    QTimer.singleShot(0, lambda: self._action_toast("✘  Blockchain unavailable.", C["RED"]))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._action_toast(f"✘  Freeze failed: {exc}", C["RED"]))
        threading.Thread(target=_do, daemon=True).start()

    def _on_vote_cancel(self):
        """Vote to cancel the flagged escrow."""
        self._action_toast("✕  Cancellation vote submitted…", C["AMBER"])
        self.cancel_btn.setEnabled(False)
        def _do():
            try:
                if CONTRACT_INSTANCE and W3_INSTANCE:
                    escrow_id = CONTRACT_INSTANCE.functions.escrowCounter().call() - 1
                    auditor_addr = W3_INSTANCE.eth.account.from_key(CURRENT_PRIVATE_KEY).address
                    CONTRACT_INSTANCE.functions.voteToCancel(escrow_id).transact({"from": auditor_addr})
                    QTimer.singleShot(0, lambda: self._action_toast(
                        f"✔  Vote cast to CANCEL escrow #{escrow_id}. Awaiting quorum.", C["AMBER"]))
                else:
                    QTimer.singleShot(0, lambda: self._action_toast("✘  Blockchain unavailable.", C["AMBER"]))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._action_toast(f"✘  Vote failed: {exc}", C["AMBER"]))
        threading.Thread(target=_do, daemon=True).start()

    def _on_mark_safe(self):
        """Clear the alert — auditor has reviewed and approved the transaction."""
        self._action_toast("✔  Transaction reviewed and marked SAFE. Alert cleared.", C["GREEN"])
        QTimer.singleShot(2000, self.clear_alert)

    def _action_toast(self, msg: str, color: str):
        self._status.setText(msg)
        self._status.setStyleSheet(f"color: {color}; font-size: 9pt; font-family: 'Segoe UI';")
        QTimer.singleShot(8000, lambda: self._status.setText(""))

    def _on_trigger_watchdog(self):
        self.watchdog_btn.setEnabled(False)
        self.watchdog_btn.setText("  ⏳  RUNNING WATCHDOG …")
        self._status.setText("// Watchdog pipeline running …")
        self._worker = WatchdogWorker(aes_key=CURRENT_PRIVATE_KEY)
        self._worker.finished.connect(self._on_watchdog_done)
        self._worker.error.connect(self._on_watchdog_error)
        self._worker.start()

    def _on_watchdog_done(self, result: dict):
        self.watchdog_btn.setEnabled(True)
        self.watchdog_btn.setText("  ▶  TRIGGER WATCHDOG TEST")
        self._status.setText(f"// Done — CID: {result.get('cid','N/A')}")
        self.raise_alert(result)
        self.watchdog_triggered.emit()

    def _on_watchdog_error(self, err: str):
        self.watchdog_btn.setEnabled(True)
        self.watchdog_btn.setText("  ▶  TRIGGER WATCHDOG TEST")
        self._status.setText(f"// Error: {err}")

    def _build_milestone_section(self, root):
        """Milestone submission section for Auditor panel."""
        ms_frame = QFrame()
        ms_frame.setObjectName("MilestoneFrame")
        ms_frame.setStyleSheet(f"""
            #MilestoneFrame {{
                background: {C['BG_CARD']}; border: 1px solid {C['GREEN']}44; border-radius: 8px;
            }}
        """)
        ms_lay = QVBoxLayout(ms_frame)
        ms_lay.setContentsMargins(16, 12, 16, 12)
        ms_lay.setSpacing(8)

        ms_title = QLabel("✔  MILESTONE SUBMISSION")
        ms_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        ms_title.setStyleSheet(f"color: {C['GREEN']};")
        ms_sub = QLabel(
            "As Auditor, submit a SHA-256 document hash to certify work completion.\n"
            "This unlocks fund release for escrows awaiting milestone verification."
        )
        ms_sub.setFont(QFont("Segoe UI", 8))
        ms_sub.setStyleSheet(f"color: {C['TEXT_DIM']};")
        ms_sub.setWordWrap(True)

        ms_input_row = QHBoxLayout()
        self.milestone_hash_input = QLineEdit()
        self.milestone_hash_input.setPlaceholderText("Auto-filled when you browse a PDF  —  or paste SHA-256 manually")
        self.milestone_hash_input.setFont(QFont("Consolas", 8))
        self.milestone_hash_input.setReadOnly(True)

        browse_btn = NeonButton("  📁  BROWSE CERTIFICATE", C["CYAN"])
        browse_btn.setToolTip("Select the completion certificate PDF — its SHA-256 hash will be computed automatically.")
        browse_btn.clicked.connect(self._on_browse_certificate)

        self.milestone_submit_btn = NeonButton("  ✔  SUBMIT MILESTONE", C["GREEN"])
        self.milestone_submit_btn.clicked.connect(self._on_submit_milestone)
        ms_input_row.addWidget(self.milestone_hash_input)
        ms_input_row.addWidget(browse_btn)
        ms_input_row.addWidget(self.milestone_submit_btn)

        ms_lay.addWidget(ms_title)
        ms_lay.addWidget(ms_sub)
        ms_lay.addLayout(ms_input_row)
        root.addWidget(ms_frame)

        # ── SLA Auto-Escalation ──
        esc_frame = QFrame()
        esc_frame.setObjectName("EscalateFrame")
        esc_frame.setStyleSheet(f"""
            #EscalateFrame {{
                background: {C['BG_CARD']}; border: 1px solid {C['RED']}88; border-radius: 8px;
            }}
        """)
        esc_lay = QHBoxLayout(esc_frame)
        esc_lay.setContentsMargins(16, 12, 16, 12)
        
        esc_text_lay = QVBoxLayout()
        esc_title = QLabel("⚠  DEAD-MAN SWITCH: SLA AUTO-ESCALATION")
        esc_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        esc_title.setStyleSheet(f"color: {C['RED']};")
        esc_sub = QLabel(
            "If Signers refuse to approve a valid milestone and the deadline expires,\n"
            "click here to bypass them and force-release the funds."
        )
        esc_sub.setFont(QFont("Segoe UI", 8))
        esc_sub.setStyleSheet(f"color: {C['TEXT_DIM']};")
        esc_text_lay.addWidget(esc_title)
        esc_text_lay.addWidget(esc_sub)
        
        self.esc_btn = NeonButton("  ⚠  FORCE ESCALATE & RELEASE", C["RED"])
        self.esc_btn.clicked.connect(self._on_escalate)
        
        esc_lay.addLayout(esc_text_lay)
        esc_lay.addStretch()
        esc_lay.addWidget(self.esc_btn)
        
        root.addWidget(esc_frame)

    def _on_browse_certificate(self):
        """Open file dialog, compute SHA-256, fill the milestone hash field."""
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Completion Certificate",
            os.path.expanduser("~"),
            "Documents (*.pdf *.docx *.doc *.png *.jpg *.jpeg);;All Files (*)"
        )
        if not path:
            return
        try:
            import hashlib
            sha = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha.update(chunk)
            digest = sha.hexdigest()
            self.milestone_hash_input.setReadOnly(False)
            self.milestone_hash_input.setText(digest)
            self.milestone_hash_input.setReadOnly(True)
            self._action_toast(
                f"✔  SHA-256 computed from '{os.path.basename(path)}'  —  Ready to submit.",
                C["GREEN"]
            )
        except Exception as e:
            self._action_toast(f"✘  Could not hash file: {e}", C["RED"])

    def _on_submit_milestone(self):
        if not CURRENT_PRIVATE_KEY:
            self._action_toast("⚠  Tap Auditor NFC tag first.", C["RED"])
            return
        self.milestone_submit_btn.setEnabled(False)
        raw_hash = self.milestone_hash_input.text().strip()

        def _do():
            try:
                import hashlib, time
                if not raw_hash:
                    # Auto-generate from timestamp
                    doc_hash_bytes = bytes.fromhex(
                        hashlib.sha256(str(time.time()).encode()).hexdigest()
                    )
                else:
                    h = raw_hash.lstrip("0x")
                    doc_hash_bytes = bytes.fromhex(h.zfill(64))

                escrow_id    = CONTRACT_INSTANCE.functions.escrowCounter().call() - 1
                auditor_addr = W3_INSTANCE.eth.account.from_key(CURRENT_PRIVATE_KEY).address
                CONTRACT_INSTANCE.functions.submitMilestone(
                    escrow_id, doc_hash_bytes
                ).transact({"from": auditor_addr})
                msg = f"✔  Milestone submitted for escrow #{escrow_id}. Funds unlocked if approvals met."
                QTimer.singleShot(0, lambda: self._action_toast(msg, C["GREEN"]))
                QTimer.singleShot(0, self.milestone_hash_input.clear)
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._action_toast(f"✘  {exc}", C["RED"]))
            QTimer.singleShot(0, lambda: self.milestone_submit_btn.setEnabled(True))

        threading.Thread(target=_do, daemon=True).start()


    def _on_escalate(self):
        if not CURRENT_PRIVATE_KEY:
            self._action_toast("⚠  Tap Auditor NFC tag first.", C["RED"])
            return
        
        self.esc_btn.setEnabled(False)
        self._action_toast("⏳  Triggering Auto-Escalation on latest pending escrow…", C["RED"])
        
        def _do():
            try:
                if not CONTRACT_INSTANCE or not W3_INSTANCE:
                    raise Exception("Blockchain not ready")
                escrow_id = CONTRACT_INSTANCE.functions.escrowCounter().call() - 1
                if escrow_id < 0:
                    raise Exception("No escrows exist")
                addr = W3_INSTANCE.eth.account.from_key(CURRENT_PRIVATE_KEY).address
                CONTRACT_INSTANCE.functions.escalateAndRelease(escrow_id).transact({"from": addr})
                QTimer.singleShot(0, lambda: self._action_toast(f"⚠  SUCCESS: Escrow #{escrow_id} Escalated & Released!", C["RED"]))
            except Exception as exc:
                err_msg = str(exc)
                if "Deadline not passed" in err_msg:
                    msg = "✘  SLA Deadline has not expired yet."
                elif "Milestone not met" in err_msg:
                    msg = "✘  Milestone must be submitted first."
                else:
                    msg = f"✘  Escalation failed: {err_msg}"
                QTimer.singleShot(0, lambda: self._action_toast(msg, C["RED"]))
            finally:
                QTimer.singleShot(0, lambda: self.esc_btn.setEnabled(True))
        
        threading.Thread(target=_do, daemon=True).start()


# ────────────────────────────────────────────────────────────
#  SIDEBAR & TOPBAR
# ────────────────────────────────────────────────────────────

class Sidebar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(210)
        self.setStyleSheet(f"background: {C['BG_SIDEBAR']}; border-right: 1px solid {C['BORDER']};")
        self._block_num = 19_203_471
        self._build_ui()
        self.update_permissions()

        self._block_timer = QTimer(self)
        self._block_timer.timeout.connect(self._update_block)
        self._block_timer.start(12000)

    def _update_block(self):
        if W3_INSTANCE and W3_INSTANCE.is_connected():
            try:
                self._block_num = W3_INSTANCE.eth.block_number
            except:
                pass
        else:
            self._block_num += 1
        self.block_lbl.setText(f"Block #{self._block_num:,}")

    def update_permissions(self):
        # Public Feed is ALWAYS accessible regardless of role
        self.btn_feed.setEnabled(True)
        self.btn_feed.setText("Public Feed")

        if CURRENT_ROLE == "ADMIN":
            # Admin: Public Feed ✅  |  Admin Panel ✅  |  Auditor Panel 🔒
            self.btn_admin.setEnabled(True)
            self.btn_auditor.setEnabled(False)
            self.btn_admin.setText("Admin Panel")
            self.btn_auditor.setText("Auditor (Locked)")
        elif CURRENT_ROLE == "AUDITOR":
            # Auditor: Public Feed ✅  |  Admin Panel 🔒  |  Auditor Panel ✅
            self.btn_admin.setEnabled(False)
            self.btn_auditor.setEnabled(True)
            self.btn_admin.setText("Admin (Locked)")
            self.btn_auditor.setText("Auditor Panel")
        elif CURRENT_ROLE == "USER":
            self.btn_admin.setEnabled(False)
            self.btn_auditor.setEnabled(False)
            self.btn_admin.setText("Admin (Locked)")
            self.btn_auditor.setText("Auditor (Locked)")
        else:  # PUBLIC
            self.btn_admin.setEnabled(False)
            self.btn_auditor.setEnabled(False)
            self.btn_admin.setText("Admin (Locked)")
            self.btn_auditor.setText("Auditor (Locked)")

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        logo_frame = QFrame()
        logo_frame.setStyleSheet(f"background: {C['BG_SIDEBAR']}; border-bottom: 1px solid {C['BORDER']};")
        logo_frame.setFixedHeight(64)
        logo_lay = QVBoxLayout(logo_frame)
        logo_lay.setContentsMargins(16, 0, 16, 0)
        logo_lbl = QLabel("◈ LEDGER NEXUS")
        logo_lbl.setFont(LOGO_FONT)
        logo_lbl.setStyleSheet(f"color: {C['CYAN']};")
        logo_lbl.setGraphicsEffect(_glow_effect(C["CYAN"], 14))
        logo_lay.addWidget(logo_lbl)
        sub_lbl = QLabel("Public Funds Tracker v1.0")
        sub_lbl.setFont(QFont("Segoe UI", 7))
        sub_lbl.setStyleSheet(f"color: {C['TEXT_DIM']};")
        logo_lay.addWidget(sub_lbl)
        root.addWidget(logo_frame)

        root.addSpacing(12)
        self.btn_feed    = SidebarButton("Public Feed",   "📡")
        self.btn_admin   = SidebarButton("Admin Panel",   "⬡")
        self.btn_auditor = SidebarButton("Auditor Panel", "⚠")

        for btn in (self.btn_feed, self.btn_admin, self.btn_auditor):
            root.addWidget(btn)
        root.addStretch()

        footer = QFrame()
        footer.setStyleSheet(f"border-top: 1px solid {C['BORDER']}; background: {C['BG_SIDEBAR']};")
        footer_lay = QVBoxLayout(footer)
        footer_lay.setContentsMargins(14, 10, 14, 14)
        footer_lay.setSpacing(6)

        net_row = QHBoxLayout()
        net_dot = StatusDot(C["GREEN"], 8)
        net_lbl = QLabel("CHAIN CONNECTED")
        net_lbl.setFont(QFont("Segoe UI", 7, QFont.Bold))
        net_lbl.setStyleSheet(f"color: {C['GREEN']};")
        net_row.addWidget(net_dot)
        net_row.addWidget(net_lbl)
        net_row.addStretch()
        footer_lay.addLayout(net_row)

        self.block_lbl = QLabel(f"Block #{self._block_num:,}")
        self.block_lbl.setFont(QFont("Consolas", 7))
        self.block_lbl.setStyleSheet(f"color: {C['TEXT_DIM']};")
        footer_lay.addWidget(self.block_lbl)
        root.addWidget(footer)


class TopBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setStyleSheet(f"background: {C['BG_CARD']}; border-bottom: 1px solid {C['BORDER']};")
        self._build_ui()
        self.update_role_status()

    def update_role_status(self):
        # Update NFC status
        has_key = CURRENT_PRIVATE_KEY is not None
        text = "🟢 AUTHENTICATED" if has_key else "🔴 NO KEY"
        color = C["GREEN"] if has_key else C["RED"]
        self.nfc_badge.setText(f"  {text}  ")
        self.nfc_badge.setStyleSheet(f"background: {color}11; border: 1px solid {color}; border-radius: 3px; color: {color}; padding: 2px 8px;")
        
        # Update Role label
        self.role_badge.setText(f"  ⬡  {CURRENT_ROLE}  ")
        self.role_badge.setStyleSheet(f"""
            background: {CURRENT_COLOR}22; border: 1px solid {CURRENT_COLOR};
            border-radius: 3px; color: {CURRENT_COLOR}; padding: 2px 8px;
        """)

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 0)

        time_lbl = QLabel(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        time_lbl.setFont(QFont("Consolas", 8))
        time_lbl.setStyleSheet(f"color: {C['TEXT_DIM']};")
        self._time_lbl = time_lbl

        timer = QTimer(self)
        timer.timeout.connect(self._update_time)
        timer.start(1000)

        self.nfc_badge = QLabel()
        self.nfc_badge.setFont(QFont("Consolas", 8))
        
        self.role_badge = QLabel()
        self.role_badge.setFont(QFont("Consolas", 8, QFont.Bold))

        ipfs_badge = QLabel("  IPFS ONLINE  ")
        ipfs_badge.setFont(QFont("Consolas", 8))
        ipfs_badge.setStyleSheet(f"""
            background: {C['CYAN']}11; border: 1px solid {C['CYAN_DIM']};
            border-radius: 3px; color: {C['CYAN_DIM']}; padding: 2px 8px;
        """)

        lay.addWidget(time_lbl)
        lay.addStretch()
        lay.addWidget(self.nfc_badge)
        lay.addSpacing(10)
        lay.addWidget(ipfs_badge)
        lay.addSpacing(10)
        lay.addWidget(self.role_badge)

    def _update_time(self):
        self._time_lbl.setText(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))


# ────────────────────────────────────────────────────────────
#  MAIN WINDOW
# ────────────────────────────────────────────────────────────

class LedgerNexusWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ledger Nexus — Public Funds Tracker")
        self.resize(1280, 800)
        self.setMinimumSize(1024, 640)
        self.setStyleSheet(GLOBAL_STYLESHEET)
        
        self._build_ui()
        
        # Async Web3 Init to prevent UI freeze
        self._progress = QProgressDialog("Connecting to Blockchain & Authorizing Hardware Key...", None, 0, 0, self)
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setStyleSheet("background: #0d0d2b; color: #00f5ff;")
        self._progress.show()
        
        self._web3_worker = Web3InitWorker()
        self._web3_worker.finished.connect(self._on_web3_init_done)
        self._web3_worker.start()

    def _on_web3_init_done(self, success):
        self._progress.accept()
        if success:
            # Update all UI elements based on resolved on-chain role
            self._top_bar.update_role_status()
            self._sidebar.update_permissions()
            
            # Load real transactions generated by the bootstrapper
            self._feed_panel.populate_transactions()
            self._feed_panel._refresh_stats()

            # If user is PUBLIC, force them to the feed panel
            if CURRENT_ROLE == "PUBLIC":
                self._nav(0, self._sidebar.btn_feed)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        self._top_bar = TopBar()
        main_lay.addWidget(self._top_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = Sidebar()
        body.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        self._feed_panel    = PublicFeedPanel()
        self._admin_panel   = AdminPanel()
        self._auditor_panel = AuditorPanel()

        self._stack.addWidget(self._feed_panel)
        self._stack.addWidget(self._admin_panel)
        self._stack.addWidget(self._auditor_panel)
        body.addWidget(self._stack)
        main_lay.addLayout(body)

        sb = self._sidebar
        sb.btn_feed.setChecked(True)

        sb.btn_feed.clicked.connect(lambda: self._nav(0, sb.btn_feed))
        sb.btn_admin.clicked.connect(lambda: self._nav(1, sb.btn_admin))
        sb.btn_auditor.clicked.connect(lambda: self._nav(2, sb.btn_auditor))

        self._admin_panel.transfer_submitted.connect(self._on_transfer)
        self._admin_panel.auth_requested.connect(self._on_reauth)
        self._auditor_panel.watchdog_triggered.connect(self._on_watchdog_triggered)

    def _nav(self, idx: int, btn):
        sb = self._sidebar
        for b in (sb.btn_feed, sb.btn_admin, sb.btn_auditor):
            b.setChecked(b is btn)
        self._stack.setCurrentIndex(idx)

    def _on_reauth(self):
        """Called when a new NFC tap happens inside the dashboard."""
        self._top_bar.update_role_status()
        self._sidebar.update_permissions()
        
        if CURRENT_ROLE == "PUBLIC":
            self._nav(0, self._sidebar.btn_feed)

    def _on_transfer(self, address: str, amount: float, purpose: str):
        REAL_TRANSACTIONS.insert(0, {
            "hash":    _make_hash(),
            "from":    W3_INSTANCE.eth.account.from_key(CURRENT_PRIVATE_KEY).address if CURRENT_PRIVATE_KEY else "0xUnknown",
            "to":      address,
            "amount":  amount,
            "purpose": purpose,
            "block":   W3_INSTANCE.eth.block_number if W3_INSTANCE and W3_INSTANCE.is_connected() else 0,
            "time":    datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            "flagged": amount > 100_000,
        })
        self._feed_panel.populate_transactions()
        self._feed_panel._refresh_stats()

    def _on_watchdog_triggered(self):
        self._nav(2, self._sidebar.btn_auditor)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Ledger Nexus")
    app.setApplicationVersion("1.0.0")
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    window = LedgerNexusWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
