#!/usr/bin/env python3
# ================================================================
#  nexus_launcher.py — A.N.SXVault Production Gateway
#
#  Hardware Authentication Gateway. Replaces the demo launcher.
#  - Authenticate via iPhone NFC Hardware Key
#  - Enter Public Ledger (Read-only)
# ================================================================

import sys
import os
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'core'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'ui'))

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QFont, QColor, QPainter, QBrush

APP_VERSION = "1.0.0"

class HardwareScanWorker(QThread):
    finished = pyqtSignal(str, str)   # (private_key, raw_uid)

    def run(self):
        import nfc_wallet
        result = nfc_wallet.wait_for_hardware_tap(timeout=30)
        if result and isinstance(result, tuple):
            key, uid = result[0], result[1]
        elif result:
            key, uid = result, ""
        else:
            key, uid = "", ""
        self.finished.emit(key or "", uid or "")

class NexusGateway(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ledger Nexus — Hardware Authentication Gateway")
        self.setFixedSize(660, 500)
        self.setStyleSheet("background-color: #04040f; color: #e0e0ff;")
        self._scan_offset = 0
        self._build()

        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._animate_scanline)
        self._scan_timer.start(25)

    def _animate_scanline(self):
        self._scan_offset = (self._scan_offset + 2) % self.height()
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setOpacity(0.04)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#00f5ff")))
        p.drawRect(0, self._scan_offset, self.width(), 2)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 50, 40, 40)
        layout.setSpacing(0)

        # ── Header ───────────────────────────────────────────
        header_lbl = QLabel("LEDGER NEXUS")
        header_lbl.setFont(QFont("Consolas", 32, QFont.Bold))
        header_lbl.setAlignment(Qt.AlignCenter)
        header_lbl.setStyleSheet("color: #00f5ff; letter-spacing: 4px;")
        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(32)
        glow.setOffset(0, 0)
        glow.setColor(QColor("#00f5ff"))
        header_lbl.setGraphicsEffect(glow)
        layout.addWidget(header_lbl)

        sub_lbl = QLabel("Hardware-Entangled Public Fund Tracker")
        sub_lbl.setFont(QFont("Segoe UI", 11))
        sub_lbl.setAlignment(Qt.AlignCenter)
        sub_lbl.setStyleSheet("color: #5a5a8a; margin-top: 8px; margin-bottom: 40px;")
        layout.addWidget(sub_lbl)

        # ── Authentication Buttons ───────────────────────────
        self.auth_btn = self._make_button("◈ AUTHENTICATE VIA HARDWARE KEY", "#7b2fff")
        self.auth_btn.clicked.connect(self._on_auth_clicked)
        layout.addWidget(self.auth_btn)
        
        layout.addSpacing(16)
        
        self.public_btn = self._make_button("◉ ENTER PUBLIC LEDGER (READ-ONLY)", "#007a80")
        self.public_btn.clicked.connect(self._on_public_clicked)
        layout.addWidget(self.public_btn)

        self.status_lbl = QLabel("")
        self.status_lbl.setFont(QFont("Consolas", 10))
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setStyleSheet("color: #ffaa00; margin-top: 20px;")
        layout.addWidget(self.status_lbl)

        layout.addStretch()

        # ── Footer ───────────────────────────────────────────
        footer = QLabel(
            f"⬡ A.N.SXVault v{APP_VERSION}  •  "
            "Cryptographic keys derived in volatile RAM — never stored on disk."
        )
        footer.setFont(QFont("Consolas", 8))
        footer.setStyleSheet("color: #2a2a4a; margin-top: 8px;")
        footer.setAlignment(Qt.AlignCenter)
        footer.setWordWrap(True)
        layout.addWidget(footer)

    def _make_button(self, text: str, color: str):
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFont(QFont("Segoe UI", 11, QFont.Bold))
        btn.setMinimumHeight(60)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {color}18;
                border: 2px solid {color};
                border-radius: 8px;
                color: {color};
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                background: {color}33;
            }}
            QPushButton:disabled {{
                background: #111;
                border: 2px solid #333;
                color: #555;
            }}
        """)
        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(15)
        glow.setOffset(0, 0)
        glow.setColor(QColor(color))
        btn.setGraphicsEffect(glow)
        return btn

    def _on_auth_clicked(self):
        self.auth_btn.setEnabled(False)
        self.public_btn.setEnabled(False)
        self.status_lbl.setText("⏳ Waiting for iPhone Universal Clipboard sync... (30s)")
        
        self.worker = HardwareScanWorker()
        self.worker.finished.connect(self._on_scan_finished)
        self.worker.start()

    def _on_scan_finished(self, key: str, uid: str):
        if key:
            from config import resolve_authority
            auth = resolve_authority(uid) if uid else {"name": "Hardware Key", "badge": "HW"}
            name  = auth.get("name", "Hardware Key")
            badge = auth.get("badge", "HW")
            self.status_lbl.setText(f"✅  {name}  [{badge}]  — Loading Dashboard…")
            self.status_lbl.setStyleSheet("color: #00ff88; margin-top: 20px;")
            self._launch_dashboard(key, uid)
        else:
            self.status_lbl.setText("❌ Timeout: No hardware signature received.")
            self.status_lbl.setStyleSheet("color: #ff0033; margin-top: 20px;")
            self.auth_btn.setEnabled(True)
            self.public_btn.setEnabled(True)

    def _on_public_clicked(self):
        self.status_lbl.setText("🌐 Initializing Public Ledger...")
        self.status_lbl.setStyleSheet("color: #00f5ff; margin-top: 20px;")
        self._launch_dashboard(None)

    def _launch_dashboard(self, private_key: str, raw_uid: str = ""):
        import ui_dashboard as dash
        dash.CURRENT_PRIVATE_KEY = private_key
        # Resolve authority name/role from registry before opening the window
        if private_key and dash.W3_INSTANCE and dash.CONTRACT_INSTANCE:
            dash.CURRENT_ROLE, dash.CURRENT_COLOR = dash._resolve_role_on_chain(
                dash.W3_INSTANCE, dash.CONTRACT_INSTANCE, private_key, raw_uid
            )
        self.hide()
        self._window = dash.LedgerNexusWindow()
        self._window.show()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app.setApplicationName("Ledger Nexus")
    app.setApplicationVersion(APP_VERSION)

    launcher = NexusGateway()
    launcher.show()
    sys.exit(app.exec_())
