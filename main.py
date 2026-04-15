"""
main.py — A.N.Sx Vault | Hybrid Multi-User Engine
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
import uuid

# ── Anchor working dir to the vault root ───────────────────────────────────
VAULT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(VAULT_ROOT)

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QImage
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from cloud_dispatcher import CloudDispatcher
from security_core import SecurityCore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── C++ shatter engine ──────────────────────────────────────────────────────
_ENGINE_PATH = os.path.join(VAULT_ROOT, "libshatter.so")
try:
    _lib = ctypes.CDLL(_ENGINE_PATH)
    _lib.run_shatter_engine.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    _lib.run_shatter_engine.restype  = ctypes.c_int
    ENGINE_LOADED = True
    logger.info("Shatter engine loaded from %s", _ENGINE_PATH)
except Exception as exc:
    _lib = None
    ENGINE_LOADED = False
    logger.warning("Shatter engine unavailable (%s). UI-only mode.", exc)


# ═══════════════════════════════════════════════════════════════════════════
# NFC PROVISIONER THREAD — spawns Flask server + waits for iPhone confirm
# ═══════════════════════════════════════════════════════════════════════════

class NFCProvisionerThread(QThread):
    """Starts the NFC Provisioner Flask server and waits for the iPhone callback."""
    seed_confirmed = pyqtSignal(str)   # emits the seed when iPhone confirms
    qr_ready       = pyqtSignal(object, str)  # emits (QPixmap, url) when QR is ready

    def run(self) -> None:
        import secrets
        import socket
        import io
        import plistlib
        import threading
        from flask import Flask, send_file, request as freq, jsonify, render_template_string
        import qrcode

        seed    = f"ANSX-VAULT-SEED-{secrets.token_hex(8).upper()}"
        done    = threading.Event()
        written = {"seed": seed}

        def get_ip():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]; s.close(); return ip
            except: return "127.0.0.1"

        ip, port = get_ip(), 5050
        url = f"http://{ip}:{port}"
        confirm_url = f"{url}/confirmed"

        # Build .shortcut plist
        shortcut_plist = {
            "WFWorkflowMinimumClientVersion": 900,
            "WFWorkflowClientVersion": "2296.0",
            "WFWorkflowHasShortcutInputVariables": False,
            "WFWorkflowIcon": {"WFWorkflowIconStartColor": -2070375169, "WFWorkflowIconGlyphNumber": 59511},
            "WFWorkflowImportQuestions": [], "WFWorkflowInputContentItemClasses": [],
            "WFWorkflowOutputContentItemClasses": [], "WFWorkflowTypes": [],
            "WFWorkflowActions": [
                {
                    "WFWorkflowActionIdentifier": "is.workflow.actions.writenfc",
                    "WFWorkflowActionParameters": {
                        "WFInput": {"Value": {"string": seed}, "WFSerializationType": "WFTextTokenString"}
                    },
                },
                {
                    "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
                    "WFWorkflowActionParameters": {
                        "WFHTTPMethod": "POST", "WFURL": confirm_url,
                        "WFHTTPBodyType": "JSON",
                        "WFJSONValues": {
                            "Value": {"WFDictionaryFieldValueItems": [{
                                "WFItemType": 0,
                                "WFKey": {"Value": {"string": "seed"}, "WFSerializationType": "WFTextTokenString"},
                                "WFValue": {"Value": {"string": seed}, "WFSerializationType": "WFTextTokenString"},
                            }]},
                            "WFSerializationType": "WFDictionaryFieldValue",
                        },
                    },
                },
            ],
        }
        shortcut_bytes = plistlib.dumps(shortcut_plist, fmt=plistlib.FMT_BINARY)

        NFC_PAGE = f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>A.N.Sx NFC Setup</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{min-height:100vh;background:#090A0F;display:flex;align-items:center;justify-content:center;font-family:Courier New,monospace;color:#E0E2EA;padding:20px}}.card{{background:#11121A;border:1px solid #B14CFF;border-radius:16px;padding:32px 24px;max-width:360px;width:100%;box-shadow:0 0 40px rgba(177,76,255,.4);text-align:center}}.logo{{font-size:11px;color:#7AA2F7;letter-spacing:3px;margin-bottom:6px}}h1{{font-size:20px;font-weight:bold;color:#B14CFF;margin-bottom:6px;text-shadow:0 0 15px rgba(177,76,255,.8)}}.sub{{font-size:11px;color:#7AA2F7;margin-bottom:20px;line-height:1.6}}.seed{{background:#1A1B26;border:1px solid #24283B;border-radius:8px;padding:12px;font-size:11px;color:#00F3FF;word-break:break-all;margin-bottom:16px;font-weight:bold;cursor:pointer}}.steps{{background:#0d0e16;border:1px dashed #24283B;border-radius:8px;padding:16px;text-align:left;margin-bottom:20px;font-size:13px;line-height:1.8;color:#7AA2F7}}.steps b{{color:#E0E2EA}}.steps .em{{color:#00F3FF}}.btn{{display:block;width:100%;border:none;border-radius:10px;font-size:16px;font-weight:bold;padding:16px;cursor:pointer;margin-bottom:10px}}.btn-ok{{background:#00f3ff;color:#000;box-shadow:0 0 20px rgba(0,243,255,.4)}}.btn-sim{{background:#1A1B26;color:#7AA2F7;border:1px solid #24283B;font-size:12px;padding:10px}}.ok{{color:#39FF14;font-size:13px;margin-top:10px;display:none;text-shadow:0 0 10px rgba(57,255,20,.6)}}</style>
</head><body><div class="card">
<div class="logo">A.N.Sx VAULT SYSTEM</div>
<h1>NFC PROVISIONER</h1>
<p class="sub">Apple blocked unsigned Shortcuts.<br/>Write the tag using <b>NFC Tools</b> (App Store).</p>
<div class="seed" onclick="copySeed()" id="seedbox">{seed}</div>
<p style="font-size:10px;color:#39FF14;margin-bottom:16px;display:none" id="copymsg">Copied to clipboard!</p>
<div class="steps">
1. Tap the seed above to copy it.<br/>
2. Open <b>NFC Tools</b> app.<br/>
3. Tap <b>Write &rarr; Add a record &rarr; Text</b>.<br/>
4. Paste the seed &amp; tap <b>OK &rarr; Write</b>.<br/>
5. Hold NFC sticker to phone.<br/>
6. After writing, press Confirm below.
</div>
<button class="btn btn-ok" onclick="confirmMac()">CONFIRM TOKEN WRITTEN</button>
<button class="btn btn-sim" onclick="simulate()" style="margin-top:10px;">Simulate Testing on Mac</button>
<div class="ok" id="ok">&#10003; Mac confirmed! Vault token enrolled.</div>
</div>
<script>
function copySeed() {{
  navigator.clipboard.writeText(document.getElementById('seedbox').innerText);
  document.getElementById('copymsg').style.display='block';
}}
function confirmMac() {{
  fetch('/confirmed', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{seed: '{seed}'}})}})
  .then(() => document.getElementById('ok').style.display='block');
}}
function simulate() {{
  fetch('/simulate').then(() => document.getElementById('ok').style.display='block');
}}
</script>
</body></html>"""

        flask_app = Flask(__name__ + "_provisioner")

        @flask_app.route("/")
        def _index():
            return NFC_PAGE

        @flask_app.route("/shortcut")
        def _shortcut():
            buf = io.BytesIO(shortcut_bytes); buf.seek(0)
            return send_file(buf, mimetype="application/octet-stream",
                             as_attachment=True, download_name="ANSxVault_NFC.shortcut")

        @flask_app.route("/confirmed", methods=["POST"])
        def _confirmed():
            data = freq.get_json(silent=True) or {}
            written["seed"] = data.get("seed", seed)
            done.set()
            return jsonify({"status": "ok"})

        @flask_app.route("/simulate")
        def _simulate():
            written["seed"] = seed; done.set()
            return "<h2 style='color:#39FF14;background:#090A0F;padding:40px;font-family:monospace'>Simulated!</h2>"

        srv = threading.Thread(
            target=lambda: flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
            daemon=True
        )
        srv.start()

        # Generate QR code as QPixmap
        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf2 = io.BytesIO(); img.save(buf2, format="PNG"); buf2.seek(0)
        qdata = buf2.read()
        qimg  = QImage.fromData(bytes(qdata))
        pmap  = QPixmap.fromImage(qimg)
        self.qr_ready.emit(pmap, url)

        done.wait()  # Block until iPhone confirms
        self.seed_confirmed.emit(written["seed"])

_NFC_PREFIX  = "ANSX-VAULT-SEED-"
_POLL_INTERVAL = 0.2   # seconds


class NFCListenerThread(QThread):
    """Background thread that polls the macOS Universal Clipboard for a vault seed."""

    authorized = pyqtSignal(str)

    def run(self) -> None:
        # Zero the clipboard to prevent stale seeds from re-triggering
        subprocess.run(["pbcopy"], input=b"", check=False)
        logger.info("[NFC] Wiretap active – scanning clipboard every %.0fms …", _POLL_INTERVAL * 1000)

        while not self.isInterruptionRequested():
            try:
                data = subprocess.check_output(["pbpaste"], timeout=1).decode().strip()
                if data.startswith(_NFC_PREFIX):
                    logger.info("[NFC] Bridge triggered: seed prefix detected.")
                    subprocess.run(["pbcopy"], input=b"VAULT_LOCKED", check=False)
                    self.authorized.emit(data)
                    return
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
            time.sleep(_POLL_INTERVAL)

    def stop(self) -> None:
        self.requestInterruption()
        self.wait(2000)


class NFCLockScreen(QDialog):
    """Full-screen lock overlay that awaits an NFC tap before granting access."""

    def __init__(self, parent: Optional[QWidget] = None, target_operator: Optional[str] = None) -> None:
        super().__init__(parent)
        self.target_operator = target_operator

        self.setWindowTitle("A.N.Sx HARDWARE LOCK")
        self.setFixedSize(560, 300)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet("background-color: #0a0a0c; border: 2px solid #ff3366;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)

        msg = (
            f"OPERATOR: {target_operator}\n\nAWAITING PHYSICAL NFC TAP…"
            if target_operator else
            "SYSTEM LOCKED\n\nAWAITING PHYSICAL NFC TAP…"
        )
        self.label = QLabel(msg)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet(
            "color: #ff3366; font-size: 20px; font-family: 'Courier New'; "
            "font-weight: bold; letter-spacing: 2px;"
        )
        layout.addWidget(self.label)

        self._listener = NFCListenerThread()
        self._listener.authorized.connect(self._on_tap)
        self._listener.start()

    def _on_tap(self, seed: str) -> None:
        if self.target_operator:
            if not SecurityCore.verify_login(self.target_operator, seed):
                logger.warning("[NFC] Hardware mismatch for operator '%s'.", self.target_operator)
                self.label.setText("❌ HARDWARE MISMATCH\nACCESS DENIED")
                self.label.setStyleSheet("color: #ff3333; font-size: 20px; font-weight: bold;")
                # Restart listener for another attempt
                self._listener = NFCListenerThread()
                self._listener.authorized.connect(self._on_tap)
                self._listener.start()
                return

        logger.info("[NFC] Hardware authorised for operator '%s'.", self.target_operator)
        self.setStyleSheet("background-color: #0a0a0c; border: 2px solid #00ffcc;")
        self.label.setStyleSheet(
            "color: #00ffcc; font-size: 20px; font-family: 'Courier New'; font-weight: bold;"
        )
        self.label.setText("✅ HARDWARE AUTHORISED\n\nDECRYPTING VAULT…")
        QTimer.singleShot(1200, self._safe_accept)

    def _safe_accept(self) -> None:
        self._listener.stop()
        self.accept()

    def closeEvent(self, event) -> None:
        self._listener.stop()
        super().closeEvent(event)


# ═══════════════════════════════════════════════════════════════════════════
# WORKER THREADS
# ═══════════════════════════════════════════════════════════════════════════

class ShatterWorker(QThread):
    """Runs the native C++ shatter engine on a background thread."""

    finished = pyqtSignal(int)

    def __init__(self, target_file: str, nfc_key: str) -> None:
        super().__init__()
        self._target_file = target_file
        self._nfc_key     = nfc_key

    def run(self) -> None:
        if not ENGINE_LOADED:
            time.sleep(1.5)   # simulate work during UI testing
            self.finished.emit(0)
            return
        result = _lib.run_shatter_engine(
            self._target_file.encode("utf-8"),
            self._nfc_key.encode("utf-8"),
        )
        self.finished.emit(result)


class DispatchWorker(QThread):
    """Uploads all 11 shards to their respective cloud targets."""

    progress = pyqtSignal(int, int)      # (shard_index, percent)
    finished = pyqtSignal()

    def run(self) -> None:
        # Credentials are resolved by CloudDispatcher from env / ~/.aws
        dispatcher = CloudDispatcher()
        threads: list[threading.Thread] = []
        import os
        base_dir = os.path.expanduser("~/.ansx_vault/shards")
        for i in range(12):
            shard_path = os.path.join(base_dir, f"fragment_{i + 1}.ansx")
            t = threading.Thread(
                target=dispatcher.upload_shard,
                args=(i, shard_path, self.progress.emit),
                daemon=True,
            )
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        self.finished.emit()


class UnshatterWorker(QThread):
    finished = pyqtSignal(int)

    def __init__(self, shard_dir: str, output_path: str, master_key: str) -> None:
        super().__init__()
        self._shard_dir = shard_dir
        self._output_path = output_path
        self._master_key = master_key

    def run(self) -> None:
        if not ENGINE_LOADED:
            time.sleep(1.5)
            self.finished.emit(-999)
            return

        _lib.unshatter_engine.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        _lib.unshatter_engine.restype = ctypes.c_int
        res = _lib.unshatter_engine(
            self._shard_dir.encode("utf-8"),
            self._output_path.encode("utf-8"),
            self._master_key.encode("utf-8")
        )
        self.finished.emit(res)

# ═══════════════════════════════════════════════════════════════════════════
# STYLESHEET
# ═══════════════════════════════════════════════════════════════════════════

_CYBER_STYLE = """
QMainWindow                { background-color: #070709; }
QWidget                    { color: #e0e0e0; font-family: 'Arial'; }
QFrame#Sidebar             { background-color: #0a0b10; border-right: 1px solid #1a1c23; }
QLabel#Brand               { color: #00ffcc; font-size: 26px; font-weight: 900;
                             font-family: 'Courier New'; letter-spacing: 2px; }
QPushButton#NavBtn         { background: transparent; color: #666; border: none;
                             text-align: left; padding: 15px 20px; font-size: 14px;
                             font-weight: bold; }
QPushButton#NavBtn:hover   { color: #00ffcc; background: #111218;
                             border-left: 3px solid #00ffcc; }
QLabel#Header              { color: #ffffff; font-size: 32px; font-weight: bold;
                             font-family: 'Courier New'; }
QFrame#StatCard            { background-color: #0f111a; border: 1px solid #1f2233;
                             border-radius: 8px; }
QLabel#StatValue           { color: #00ffcc; font-size: 38px; font-weight: bold;
                             font-family: 'Courier New'; }
QFrame#ActionPanel         { background-color: #0c0d14; border: 1px solid #1a1c23;
                             border-radius: 12px; }
QPushButton#PrimaryBtn     { background-color: #0d47a1; color: white; border-radius: 6px;
                             font-weight: bold; font-size: 16px; height: 60px; }
QPushButton#PrimaryBtn:hover{ background-color: #1565c0; border: 1px solid #00ffcc; }
QPushButton#PrimaryBtn:disabled { background-color: #1a1c23; color: #555; border: none; }
QLineEdit                  { background-color: #0a0b10; border: 1px solid #1f2233;
                             color: #00ffcc; padding: 15px; font-size: 16px;
                             font-family: 'Courier New'; border-radius: 6px; }
QTextEdit                  { background-color: #070709; border: 1px solid #1f2233;
                             color: #00ffcc; font-family: 'Courier New'; font-size: 12px; }
QProgressBar               { border: 1px solid #1f2233; background: #0a0b10;
                             height: 8px; border-radius: 4px;
                             text-align: center; color: transparent; }
QProgressBar::chunk        { background-color: #00ffcc; border-radius: 4px; }
"""


# ═══════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════════════════

class ANSxVault(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.current_operator: str = ""

        self.setWindowTitle("A.N.Sx Vault | Hybrid Multi-User Engine")
        self.resize(1200, 800)
        self.setStyleSheet(_CYBER_STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        self._main_layout = QHBoxLayout(central)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        self._build_sidebar()

        self._stack = QStackedWidget()
        self._main_layout.addWidget(self._stack)

        # Pages
        self._page_registration = QWidget()
        self._build_registration_ui()
        self._stack.addWidget(self._page_registration)

        self._page_vault = QWidget()
        self._build_vault_ui()
        self._stack.addWidget(self._page_vault)

        self._page_send = QWidget()
        self._build_send_ui()
        self._stack.addWidget(self._page_send)

        self._page_receive = QWidget()
        self._build_receive_ui()
        self._stack.addWidget(self._page_receive)

        self._page_secrets = QWidget()
        self._build_secrets_ui()
        self._stack.addWidget(self._page_secrets)

        # Background UDP P2P Listener
        try:
            from udp_courier import UDPListenerDaemon
            self._udp_daemon = UDPListenerDaemon()
            self._udp_daemon.incoming_file.connect(self._on_incoming_udp)
            self._udp_daemon.start()
        except Exception as e:
            logger.error("Failed to start UDP Daemon: %s", e)

        # Delayed boot prevents the invisible deadlock on macOS
        QTimer.singleShot(150, self._boot_sequence)

    def _on_incoming_udp(self, filepath: str) -> None:
        QMessageBox.information(
            self,
            "INCOMING P2P TRANSFER", 
            f"An authorized Ghost Map payload was beamed directly to your IP!\n\nSaved locally to: {filepath}\n\nSwitch to the RECEIVE Stage and select it to reconstruct your file."
        )

    # ── Boot ────────────────────────────────────────────────────────────────

    def _boot_sequence(self) -> None:
        users = SecurityCore.list_registered_users()
        if not users:
            self._stack.setCurrentWidget(self._page_registration)
        else:
            self._show_login_selector(users)

    def _show_login_selector(self, users: list[str]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("A.N.Sx :: AUTHENTICATION")
        dialog.setFixedSize(460, 80 + 60 * len(users))
        dialog.setStyleSheet("background-color: #0a0a0c; border: 1px solid #00ffcc;")

        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)

        title = QLabel("SYSTEM OPERATOR ACCESS")
        title.setStyleSheet("color: #00ffcc; font-size: 18px; font-weight: bold; margin-bottom: 15px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        for user in users:
            btn = QPushButton(f"  LOGIN: {user.upper()}")
            btn.setFixedHeight(55)
            btn.setStyleSheet(
                "QPushButton { background-color: #111; color: #ddd; text-align: left; "
                "padding-left: 20px; border: 1px solid #222; font-weight: bold; } "
                "QPushButton:hover { background-color: #1a1a1a; border: 1px solid #00ffcc; color: #00ffcc; }"
            )
            btn.clicked.connect(lambda _, u=user: self._trigger_nfc_auth(u, dialog))
            layout.addWidget(btn)

        reg_btn = QPushButton("+ REGISTER NEW HARDWARE IDENTITY")
        reg_btn.setStyleSheet(
            "color: #ff9900; margin-top: 25px; border: none; font-size: 12px; font-weight: bold;"
        )
        reg_btn.clicked.connect(lambda: [dialog.done(0), self._stack.setCurrentWidget(self._page_registration)])
        layout.addWidget(reg_btn)

        dialog.exec()

    def _trigger_nfc_auth(self, username: str, dialog: QDialog) -> None:
        dialog.accept()
        self.current_operator = username
        lock = NFCLockScreen(self, target_operator=username)
        if lock.exec():
            self._op_label.setText(f"OP: {self.current_operator}")
            self._stack.setCurrentWidget(self._page_vault)
            logger.info("ACCESS GRANTED — operator '%s' online.", username)

    # ── Sidebar ─────────────────────────────────────────────────────────────

    def _build_sidebar(self) -> None:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(260)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 30, 0, 30)

        brand = QLabel("A.N.Sx VAULT")
        brand.setObjectName("Brand")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(brand)
        layout.addSpacing(40)

        def _nav_btn(label: str) -> QPushButton:
            btn = QPushButton(f"  {label}")
            btn.setObjectName("NavBtn")
            layout.addWidget(btn)
            return btn

        nav_vault   = _nav_btn("🔐 VAULT FILE")
        nav_vault.setStyleSheet("color: #00ffcc; border-left: 3px solid #00ffcc;")
        nav_send    = _nav_btn("✉️ SEND (GHOST MAP)")
        nav_receive = _nav_btn("📥 UNSHATTER (RECEIVE)")
        nav_secrets = _nav_btn("📒 CONTACT BOOK")

        nav_vault.clicked.connect(lambda: self._stack.setCurrentWidget(self._page_vault))
        nav_send.clicked.connect(lambda: self._stack.setCurrentWidget(self._page_send))
        nav_receive.clicked.connect(lambda: self._stack.setCurrentWidget(self._page_receive))
        nav_secrets.clicked.connect(lambda: self._stack.setCurrentWidget(self._page_secrets))

        lock_btn = QPushButton("  🔒 LOCK VAULT")
        lock_btn.setObjectName("NavBtn")
        lock_btn.setStyleSheet("color: #ff3366; font-weight: bold; margin-top: 10px;")
        lock_btn.clicked.connect(self._lock_vault)
        layout.addWidget(lock_btn)

        layout.addStretch()

        profile_frame = QFrame()
        profile_layout = QVBoxLayout(profile_frame)
        self._op_label = QLabel("OP: UNAUTHENTICATED")
        self._op_label.setStyleSheet("color: white; font-weight: bold; font-size: 13px;")
        status_label = QLabel("● NFC HARDWARE LINKED")
        status_label.setStyleSheet("color: #00ffcc; font-size: 10px; font-weight: bold;")
        profile_layout.addWidget(self._op_label)
        profile_layout.addWidget(status_label)
        layout.addWidget(profile_frame)

        self._main_layout.addWidget(sidebar)

    def _lock_vault(self) -> None:
        logger.info("Terminating session for operator '%s'.", self.current_operator or "unknown")
        self.current_operator = ""
        self._op_label.setText("OP: UNAUTHENTICATED")
        self._boot_sequence()

        name = self._name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Operator Alias Required.")
            return

        self._nfc_btn.setEnabled(False)
        self._name_input.setEnabled(False)
        self._terminal_out.append(f"> INITIATING BINDING SEQUENCE FOR: {name.upper()}")
        QApplication.processEvents()

        self._terminal_out.append("> ACQUIRING HARDWARE UUID LOCK...")
        QApplication.processEvents()
        machine_id = SecurityCore.get_machine_id()
        self._terminal_out.append(f"> [OK] MACHINE LOCKED: {machine_id}")

        self._terminal_out.append("> ACQUIRING GEOSPATIAL ENTANGLEMENT...")
        QApplication.processEvents()
        geo = SecurityCore.get_geolocation()
        self._terminal_out.append(f"> [OK] SPATIAL LOCK ASSIGNED: {geo}")

        self._terminal_out.append("> LAUNCHING NFC PROVISIONER — SCAN QR WITH iPHONE...")
        QApplication.processEvents()

        # Start the provisioner thread
        self._provisioner = NFCProvisionerThread()
        self._provisioner.qr_ready.connect(self._show_qr_dialog)
        self._provisioner.seed_confirmed.connect(self._finalize_registration)
        self._provisioner.start()

    def _show_qr_dialog(self, pixmap: "QPixmap", url: str) -> None:
        """Pops up a QR code dialog inside the app while waiting for iPhone."""
        self._qr_dialog = QDialog(self)
        self._qr_dialog.setWindowTitle("Scan with iPhone to provision NFC sticker")
        self._qr_dialog.setStyleSheet("background-color: #090A0F; color: #E0E2EA; font-family: Courier New;")
        self._qr_dialog.setFixedSize(400, 480)

        layout = QVBoxLayout(self._qr_dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("📡 A.N.Sx NFC PROVISIONER")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #B14CFF; font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        qr_lbl = QLabel()
        qr_lbl.setPixmap(pixmap.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
        qr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(qr_lbl)

        url_lbl = QLabel(url)
        url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        url_lbl.setStyleSheet("color: #00F3FF; font-size: 12px;")
        layout.addWidget(url_lbl)

        wait_lbl = QLabel("Waiting for iPhone to write NFC sticker...")
        wait_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wait_lbl.setStyleSheet("color: #7AA2F7; font-size: 12px;")
        layout.addWidget(wait_lbl)

        bar = QProgressBar()
        bar.setRange(0, 0)  # Infinite spinner
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        layout.addWidget(bar)

        self._qr_dialog.show()

    def _build_registration_ui(self) -> None:
        """Two-panel registration screen with inline QR code provisioner."""
        root = QVBoxLayout(self._page_registration)
        root.setContentsMargins(40, 36, 40, 36)
        root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────────
        header = QLabel("⬡  A.N.Sx VAULT — OPERATOR GENESIS")
        header.setStyleSheet(
            "color: #00ffcc; font-size: 26px; font-weight: bold;"
            " font-family: 'Courier New'; letter-spacing: 2px;"
        )
        root.addWidget(header)

        sub = QLabel("Bind your cryptographic identity to this machine · GPS · NFC hardware token")
        sub.setStyleSheet("color: #7AA2F7; font-size: 12px; margin-bottom: 24px;")
        root.addWidget(sub)

        # Step indicator row
        steps_row = QHBoxLayout()
        steps_row.setSpacing(0)

        def _step_badge(n, txt, active=False):
            c = "#00ffcc" if active else "#333"
            tc = "#000" if active else "#666"
            f = QFrame()
            f.setStyleSheet(f"background: {c}; border-radius: 6px; padding: 2px 10px;")
            fl = QHBoxLayout(f); fl.setContentsMargins(10,4,10,4); fl.setSpacing(6)
            nb = QLabel(str(n))
            nb.setStyleSheet(f"color: {tc}; font-weight: bold; font-size: 13px; background: transparent;")
            nl = QLabel(txt)
            nl.setStyleSheet(f"color: {tc}; font-size: 11px; background: transparent;")
            fl.addWidget(nb); fl.addWidget(nl)
            return f

        self._step1_badge = _step_badge(1, "IDENTIFY", active=True)
        self._step2_badge = _step_badge(2, "SCAN QR")
        self._step3_badge = _step_badge(3, "CONFIRM")
        dot1 = QLabel(" ── ")
        dot1.setStyleSheet("color: #333; font-size: 11px;")
        dot2 = QLabel(" ── ")
        dot2.setStyleSheet("color: #333; font-size: 11px;")
        steps_row.addWidget(self._step1_badge)
        steps_row.addWidget(dot1)
        steps_row.addWidget(self._step2_badge)
        steps_row.addWidget(dot2)
        steps_row.addWidget(self._step3_badge)
        steps_row.addStretch()
        root.addLayout(steps_row)
        root.addSpacing(20)

        # ── Two-column body ──────────────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(24)

        # LEFT PANEL — name input + terminal log
        left = QFrame()
        left.setStyleSheet(
            "background: #0a0b12; border: 1px solid #1a1c28; border-radius: 10px;"
        )
        ll = QVBoxLayout(left)
        ll.setContentsMargins(24, 24, 24, 24)
        ll.setSpacing(12)

        lbl_alias = QLabel("> STEP 1 — Enter Operator Alias")
        lbl_alias.setStyleSheet("color: #00ffcc; font-size: 12px; font-weight: bold;")
        ll.addWidget(lbl_alias)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("e.g.  adarsh_alpha")
        self._name_input.setFixedHeight(46)
        self._name_input.setStyleSheet(
            "background: #0f1520; color: #00ffcc; padding: 10px 14px;"
            " font-weight: bold; font-size: 14px;"
            " border: 1px solid #00ffcc; border-radius: 6px;"
        )
        ll.addWidget(self._name_input)

        self._nfc_btn = QPushButton("⚡  BEGIN GENESIS — GENERATE QR")
        self._nfc_btn.setObjectName("PrimaryBtn")
        self._nfc_btn.setFixedHeight(48)
        self._nfc_btn.clicked.connect(self._run_genesis)
        ll.addWidget(self._nfc_btn)

        sep = QLabel("── BINDING LOG ──────────────────────────────")
        sep.setStyleSheet("color: #222; font-size: 10px; margin-top: 6px;")
        ll.addWidget(sep)

        self._terminal_out = QTextEdit()
        self._terminal_out.setReadOnly(True)
        self._terminal_out.setStyleSheet(
            "background: #040508; color: #00ffcc;"
            " border: 1px solid #111; font-family: 'Courier New'; font-size: 11px;"
        )
        ll.addWidget(self._terminal_out)

        body.addWidget(left, stretch=3)

        # RIGHT PANEL — QR code + instructions
        right = QFrame()
        right.setStyleSheet(
            "background: #0a0b12; border: 1px solid #1a1c28; border-radius: 10px;"
        )
        rl = QVBoxLayout(right)
        rl.setContentsMargins(24, 24, 24, 24)
        rl.setSpacing(12)
        rl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self._qr_placeholder = QLabel("📱")
        self._qr_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_placeholder.setFixedSize(260, 260)
        self._qr_placeholder.setStyleSheet(
            "background: #111; border: 2px dashed #222; border-radius: 12px;"
            " font-size: 60px;"
        )
        rl.addWidget(self._qr_placeholder, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._qr_status = QLabel("QR will appear here after you\nclick BEGIN GENESIS")
        self._qr_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_status.setStyleSheet(
            "color: #555; font-size: 12px; font-family: 'Courier New'; margin-top: 8px;"
        )
        rl.addWidget(self._qr_status)

        self._qr_url_label = QLabel("")
        self._qr_url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_url_label.setStyleSheet(
            "color: #00F3FF; font-size: 11px; font-family: 'Courier New';"
        )
        self._qr_url_label.setWordWrap(True)
        rl.addWidget(self._qr_url_label)

        # Mini instruction panel
        instr_box = QFrame()
        instr_box.setStyleSheet(
            "background: #0d0e16; border: 1px dashed #1a1c28; border-radius: 8px; padding: 4px;"
        )
        ib = QVBoxLayout(instr_box)
        ib.setContentsMargins(12, 10, 12, 10)
        ib.setSpacing(4)
        steps = [
            "① Scan QR with iPhone Camera",
            "② Tap page → Download Shortcut",
            "③ Install → Run → Hold NFC sticker",
            "④ Mac auto-confirms ✓",
        ]
        for s in steps:
            sl = QLabel(s)
            sl.setStyleSheet("color: #7AA2F7; font-size: 11px; background: transparent;")
            ib.addWidget(sl)
        rl.addWidget(instr_box)

        # Simulate button (for same-machine testing)
        self._sim_btn = QPushButton("🖥  Simulate NFC (same machine)")
        self._sim_btn.setEnabled(False)
        self._sim_btn.setStyleSheet(
            "color: #7AA2F7; background: #111; border: 1px solid #222;"
            " border-radius: 6px; font-size: 11px; padding: 8px;"
        )
        self._sim_btn.clicked.connect(self._simulate_nfc)
        rl.addWidget(self._sim_btn)
        rl.addStretch()

        body.addWidget(right, stretch=2)
        root.addLayout(body)

    def _simulate_nfc(self) -> None:
        """Triggers the /simulate endpoint on the local Flask server."""
        try:
            import urllib.request
            urllib.request.urlopen(
                f"http://127.0.0.1:5050/simulate", timeout=2
            )
            self._terminal_out.append("> [SIM] Simulate endpoint triggered.")
        except Exception as e:
            self._terminal_out.append(f"> [SIM] Could not reach server: {e}")

    def _run_genesis(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Operator Alias Required.")
            return

        self._nfc_btn.setEnabled(False)
        self._name_input.setEnabled(False)

        self._terminal_out.append(f"> INITIATING BINDING SEQUENCE FOR: {name.upper()}")
        QApplication.processEvents()

        self._terminal_out.append("> ACQUIRING HARDWARE UUID LOCK...")
        QApplication.processEvents()
        machine_id = SecurityCore.get_machine_id()
        self._terminal_out.append(f"> [OK] MACHINE LOCKED: {machine_id[:20]}…")

        self._terminal_out.append("> ACQUIRING GEOSPATIAL ENTANGLEMENT...")
        QApplication.processEvents()
        geo = SecurityCore.get_geolocation()
        self._terminal_out.append(f"> [OK] SPATIAL ANCHOR: {geo}")

        self._terminal_out.append("> STARTING NFC PROVISIONER SERVER...")
        QApplication.processEvents()

        # Activate step 2 badge
        self._step2_badge.setStyleSheet(
            "background: #00ffcc; border-radius: 6px; padding: 2px 10px;"
        )

        self._provisioner = NFCProvisionerThread()
        self._provisioner.qr_ready.connect(self._on_qr_ready)
        self._provisioner.seed_confirmed.connect(self._finalize_registration)
        self._provisioner.start()

    def _on_qr_ready(self, pixmap: QPixmap, url: str) -> None:
        """Called by NFCProvisionerThread when QR + Flask server are ready."""
        # Show QR code inline in the right panel
        self._qr_placeholder.setPixmap(
            pixmap.scaled(260, 260,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
        )
        self._qr_placeholder.setStyleSheet(
            "background: white; border: 2px solid #00ffcc; border-radius: 12px;"
        )
        self._qr_status.setText("📡 QR READY\nScan with iPhone Camera")
        self._qr_status.setStyleSheet(
            "color: #00ffcc; font-size: 12px; font-weight: bold;"
            " font-family: 'Courier New'; margin-top: 8px;"
        )
        self._qr_url_label.setText(url)
        self._sim_btn.setEnabled(True)   # allow same-machine simulation

        self._terminal_out.append(f"> [OK] PROVISIONER SERVER ONLINE: {url}")
        self._terminal_out.append("> WAITING FOR IPHONE NFC CONFIRMATION...")

    def _finalize_registration(self, nfc_seed: str) -> None:
        name = self._name_input.text().strip()

        # Activate step 3 badge
        self._step3_badge.setStyleSheet(
            "background: #00ffcc; border-radius: 6px; padding: 2px 10px;"
        )
        self._qr_status.setText("✅ NFC CONFIRMED\nBinding identity...") 
        self._qr_status.setStyleSheet(
            "color: #39FF14; font-size: 12px; font-weight: bold;"
            " font-family: 'Courier New'; margin-top: 8px;"
        )
        self._sim_btn.setEnabled(False)

        self._terminal_out.append(f"> [OK] HARDWARE TOKEN DETECTED: {nfc_seed[:18]}…")
        self._terminal_out.append("> ENGAGING PBKDF2 ENTANGLEMENT ENGINE (600,000 PASSES)…")
        self._terminal_out.append("> FORGING RSA-4096 KEYS & SECURING IDENTITY…")
        QApplication.processEvents()

        try:
            vault_id = SecurityCore.establish_identity(name, nfc_seed)
            self._terminal_out.append(f"> [SUCCESS] OPERATOR IDENTITY SECURED.")
            self._terminal_out.append(f"> VAULT ID: {vault_id}")
            self._terminal_out.append("> ACCESS GRANTED. LOADING COMMAND CENTER…")

            self.current_operator = name
            self._op_label.setText(f"OP: {name}")
            QTimer.singleShot(3500, lambda: self._stack.setCurrentWidget(self._page_vault))
        except Exception as exc:
            logger.exception("Identity forge failed.")
            self._terminal_out.append(f"> CRITICAL FORGE FAILURE: {exc}")
            self._nfc_btn.setEnabled(True)
            self._name_input.setEnabled(True)

    # ── Dashboard ────────────────────────────────────────────────────────────

    def _build_dashboard(self) -> None:
        layout = QVBoxLayout(self._page_dashboard)
        layout.setContentsMargins(60, 50, 60, 50)

        header = QLabel("SYSTEM OVERVIEW")
        header.setObjectName("Header")
        layout.addWidget(header)
        layout.addSpacing(20)

        stats = QHBoxLayout()
        stats.addWidget(self._create_stat_card("ACTIVE SHARDS",  "11",       "#00ffcc"))
        stats.addWidget(self._create_stat_card("LOCAL ANCHORS", "1",         "#ff9900"))
        stats.addWidget(self._create_stat_card("ENCRYPTION",    "RSA-4096",  "#00ffcc"))
        layout.addLayout(stats)
        layout.addSpacing(40)

        action_panel = QFrame()
        action_panel.setObjectName("ActionPanel")
        ap_layout = QVBoxLayout(action_panel)
        ap_layout.setContentsMargins(40, 40, 40, 40)

        # ─── CONTACT BOOK & STEGANOGRAPHY UI ───
        contacts_layout = QHBoxLayout()
        self._export_btn = QPushButton("EXPORT MY ID")
        self._export_btn.clicked.connect(self._export_id)
        self._import_btn = QPushButton("IMPORT CONTACT")
        self._import_btn.clicked.connect(self._import_contact)
        
        self._receiver_dropdown = QComboBox()
        self._receiver_dropdown.setStyleSheet("background-color: #0f1520; color: #00ffcc; padding: 5px;")
        self._refresh_contacts_dropdown()
        
        contacts_layout.addWidget(self._export_btn)
        contacts_layout.addWidget(self._import_btn)
        
        rx_label = QLabel("TARGET RECEIVER:")
        rx_label.setStyleSheet("color: #aaa;")
        contacts_layout.addWidget(rx_label)
        contacts_layout.addWidget(self._receiver_dropdown)
        
        ap_layout.addLayout(contacts_layout)
        ap_layout.addSpacing(20)
        # ────────────────────────────────────────

        self._panel_title = QLabel("AWAITING BIG DATA PAYLOAD")
        self._panel_title.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        self._panel_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ap_layout.addWidget(self._panel_title)

        self._progress_bar = QProgressBar()
        self._progress_bar.hide()
        ap_layout.addWidget(self._progress_bar)

        self._shatter_btn = QPushButton("SELECT FILE & ENGAGE ENGINE")
        self._shatter_btn.setObjectName("PrimaryBtn")
        self._shatter_btn.clicked.connect(self._initiate_shatter)
        ap_layout.addWidget(self._shatter_btn)

        layout.addWidget(action_panel)
        layout.addStretch()

    def _refresh_contacts_dropdown(self) -> None:
        self._receiver_dropdown.clear()
        self._receiver_dropdown.addItem("SELECT RECEIVER...")
        contacts = SecurityCore.get_contacts()
        for name, pub_key in contacts.items():
            self._receiver_dropdown.addItem(name, pub_key)

    def _export_id(self) -> None:
        target_dir = QFileDialog.getExistingDirectory(self, "Select Export Directory")
        if target_dir:
            try:
                path = SecurityCore.export_public_identity(self.current_operator, target_dir)
                QMessageBox.information(self, "Identity Exported", f"Public ID saved to:\n{path}\n\nEmail this file to your associates.")
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", str(e))

    def _import_contact(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Contact ID", "", "ANSX ID (*.ansx_id)")
        if file_path:
            try:
                name = SecurityCore.import_contact(file_path)
                QMessageBox.information(self, "Contact Secured", f"Public Key for '{name}' strictly imported via PKI.")
                self._refresh_contacts_dropdown()
            except Exception as e:
                QMessageBox.critical(self, "Import Error", str(e))

    def _initiate_shatter(self) -> None:
        receiver_idx = self._receiver_dropdown.currentIndex()
        if receiver_idx == 0:
            QMessageBox.warning(self, "Security Lock", "You must select a Target Receiver from the Contact Book.")
            return
            
        receiver_pub_key = self._receiver_dropdown.itemData(receiver_idx)

        carrier_img, _ = QFileDialog.getOpenFileName(self, "Select Carrier Image (Ghost Map)", "", "Images (*.png *.jpg)")
        if not carrier_img:
            QMessageBox.information(self, "Ghost Map Req", "Select an image (like a logo) to hide the 12th Shard inside.")
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "Select Big Data Payload", "", "All Files (*)")
        if not file_path:
            return

        identity = SecurityCore.load_identity_for_user(self.current_operator)
        if not identity:
            QMessageBox.critical(self, "Error", "No identity loaded. Please log in again.")
            return

        self._shatter_btn.setEnabled(False)
        self._shatter_btn.setText("SHATTERING…")
        self._panel_title.setText(">> COMPUTING GALOIS FIELD & ENTANGLING SHARDS <<")
        self._panel_title.setStyleSheet(
            "color: #ff3366; font-size: 20px; font-weight: bold; font-family: 'Courier New';"
        )
        self._progress_bar.show()
        self._progress_bar.setRange(0, 0)   # indeterminate pulse

        # The Ephemeral 12th Shard Master Key
        ephemeral_master_key = os.urandom(32).hex()

        # Generate Steganography Carrier Image
        out_courier = os.path.join(os.path.expanduser("~/Desktop"), "payload_courier.png")
        try:
            from ghost_map import GhostMap
            GhostMap.hide_key_in_image(
                ephemeral_master_key.encode('utf-8'),
                receiver_pub_key, 
                carrier_img, 
                out_courier
            )
            self._terminal_out.append(f"> [GHOST MAP] 12TH SHARD RSA-BOUND AND EMBEDDED IN IMAGE.")
            self._terminal_out.append(f"> [GHOST MAP] SAVED TO: {out_courier}")
            QApplication.processEvents()
        except Exception as e:
            QMessageBox.critical(self, "Ghost Map Error", str(e))
            self._shatter_btn.setEnabled(True)
            self._shatter_btn.setText("SELECT FILE & ENGAGE ENGINE")
            self._progress_bar.hide()
            return

        self._shatter_worker = ShatterWorker(file_path, ephemeral_master_key)
        self._shatter_worker.finished.connect(self._on_shatter_complete)
        QTimer.singleShot(800, self._shatter_worker.start)

    def _on_shatter_complete(self, exit_code: int) -> None:
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(100)

        if exit_code == 0:
            self._panel_title.setText("PAYLOAD SECURED: 12 REED-SOLOMON SHARDS FORGED.")
            self._panel_title.setStyleSheet("color: #00ffcc; font-size: 18px; font-weight: bold;")
            self._shatter_btn.setText("DISPATCH SHARDS TO CLOUD")
            self._shatter_btn.clicked.disconnect()
            self._shatter_btn.clicked.connect(self._start_dispatch)
            self._shatter_btn.setEnabled(True)
        else:
            self._panel_title.setText(f"ENGINE FAILURE: CODE {exit_code}")
            self._panel_title.setStyleSheet("color: #ff3333;")
            self._shatter_btn.setText("RETRY")
            self._shatter_btn.setEnabled(True)

    # ── Logistics ───────────────────────────────────────────────────────────

    def _build_logistics_ui(self) -> None:
        layout = QVBoxLayout(self._page_logistics)
        layout.setContentsMargins(60, 50, 60, 50)

        header = QLabel("MULTI-CLOUD DISPATCH LOGISTICS")
        header.setObjectName("Header")
        layout.addWidget(header)
        layout.addSpacing(20)

        clouds = [
            "AWS-EAST", "GCP-EU", "AZURE-ASIA", "IBM-DAL", "WASABI",
            "BACKBLAZE", "AWS-SOUTH", "ORACLE", "GCP-WEST", "AZURE-GER", "DO-NYC",
        ]

        grid_frame = QFrame()
        grid_frame.setStyleSheet(
            "background-color: #0c0d14; border: 1px solid #1a1c23; border-radius: 12px;"
        )
        grid_layout = QVBoxLayout(grid_frame)
        grid_layout.setContentsMargins(30, 30, 30, 30)
        grid_layout.setSpacing(15)

        self._dispatch_bars: list[QProgressBar] = []
        for i, cloud in enumerate(clouds):
            row = QHBoxLayout()
            lbl = QLabel(f"SHARD {i + 1:02d} → {cloud}")
            lbl.setStyleSheet("color: #7a8299; font-weight: bold; font-family: 'Courier New';")
            lbl.setFixedWidth(220)
            pb = QProgressBar()
            self._dispatch_bars.append(pb)
            row.addWidget(lbl)
            row.addWidget(pb)
            grid_layout.addLayout(row)

        layout.addWidget(grid_frame)
        layout.addStretch()

    def _start_dispatch(self) -> None:
        self._stack.setCurrentWidget(self._page_logistics)
        self._dispatch_worker = DispatchWorker()
        self._dispatch_worker.progress.connect(self._update_dispatch_bar)
        self._dispatch_worker.finished.connect(
            lambda: QMessageBox.information(self, "SUCCESS", "All Shards Dispersed.")
        )
        self._dispatch_worker.start()

    def _update_dispatch_bar(self, idx: int, val: int) -> None:
        if 0 <= idx < len(self._dispatch_bars):
            self._dispatch_bars[idx].setValue(val)

    # ── Secrets ─────────────────────────────────────────────────────────────

    def _build_secrets_ui(self) -> None:
        layout = QVBoxLayout(self._page_secrets)
        layout.setContentsMargins(60, 50, 60, 50)

        header = QLabel("ZERO-KNOWLEDGE KEY EXCHANGE")
        header.setObjectName("Header")
        layout.addWidget(header)
        layout.addSpacing(20)

        layout.addWidget(QLabel("MY PUBLIC IDENTITY BLOCK:"))

        self._key_display = QTextEdit()
        self._key_display.setReadOnly(True)
        self._key_display.setStyleSheet(
            "background-color: #0c0d14; color: #555; border: 1px solid #1a1c23;"
        )
        layout.addWidget(self._key_display)

        copy_btn = QPushButton("COPY PUBLIC KEY")
        copy_btn.setObjectName("PrimaryBtn")
        copy_btn.setFixedHeight(50)
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self._key_display.toPlainText())
        )
        layout.addWidget(copy_btn)

    def _load_my_key_data(self) -> None:
        if not self.current_operator:
            return
        identity = SecurityCore.load_identity_for_user(self.current_operator)
        if identity:
            self._key_display.setText(identity.get("public_key", "KEY_NOT_FOUND"))

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _create_stat_card(title_text: str, value_text: str, value_color: str) -> QFrame:
        card = QFrame()
        card.setObjectName("StatCard")
        card.setFixedHeight(120)
        lyt = QVBoxLayout(card)
        title = QLabel(title_text)
        title.setStyleSheet("color: #7a8299; font-size: 11px; font-weight: bold;")
        val = QLabel(value_text)
        val.setObjectName("StatValue")
        val.setStyleSheet(
            f"color: {value_color}; font-size: 38px; font-weight: bold; font-family: 'Courier New';"
        )
        lyt.addWidget(title)
        lyt.addWidget(val)
        return card


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

import ui_patch
ui_patch.inject(ANSxVault, ShatterWorker, DispatchWorker, UnshatterWorker)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ANSxVault()
    window.show()
    sys.exit(app.exec())