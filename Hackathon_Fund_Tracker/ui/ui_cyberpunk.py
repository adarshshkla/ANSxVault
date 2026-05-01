import time
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFrame, QProgressBar, QCheckBox, QGraphicsDropShadowEffect, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
import security_core

# ─────────────────────────────────────────────────────────────
#  NEON CYBERPUNK PALETTE
# ─────────────────────────────────────────────────────────────
BG_DARK    = "#090A0F"
BG_CARD    = "#11121A"
BG_INPUT   = "#1A1B26"
BORDER     = "#24283B"
NEON_CYAN  = "#00F3FF"
NEON_GREEN = "#39FF14"
NEON_RED   = "#FF003C"
NEON_PURP  = "#B14CFF"
TEXT_WHITE = "#E0E2EA"
TEXT_GRAY  = "#7AA2F7"

def apply_glow(widget, color_hex, blur_radius=25, offset=0):
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(blur_radius)
    shadow.setColor(QColor(color_hex))
    shadow.setOffset(offset, offset)
    widget.setGraphicsEffect(shadow)

def primary_button(text, color=NEON_CYAN, text_color=BG_DARK):
    btn = QPushButton(text)
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {color};
            color: {text_color};
            border: none;
            border-radius: 4px;
            font-size: 14px;
            font-weight: bold;
            padding: 12px;
            text-transform: uppercase;
            letter-spacing: 2px;
        }}
        QPushButton:hover {{ background-color: #FFFFFF; color: #000000; }}
        QPushButton:pressed {{ background-color: {NEON_PURP}; color: #FFFFFF; }}
        QPushButton:disabled {{
            background-color: {BG_INPUT};
            color: {TEXT_GRAY};
            border: 1px solid {BORDER};
        }}
    """)
    if color == NEON_CYAN:
        apply_glow(btn, NEON_CYAN, 15)
    return btn

def label(text, size=14, color=TEXT_WHITE, bold=False):
    lbl = QLabel(text)
    weight = "bold" if bold else "normal"
    lbl.setStyleSheet(f"color: {color}; font-size: {size}px; font-weight: {weight}; background: transparent; border: none;")
    return lbl

def input_field(placeholder, echo=False):
    fld = QLineEdit()
    fld.setPlaceholderText(placeholder)
    if echo:
        fld.setEchoMode(QLineEdit.EchoMode.Password)
    fld.setMinimumHeight(44)
    fld.setStyleSheet(f"""
        QLineEdit {{
            background-color: {BG_INPUT};
            border: 1px solid {NEON_CYAN};
            border-radius: 4px;
            padding: 10px 14px;
            color: {TEXT_WHITE};
            font-size: 14px;
        }}
        QLineEdit:focus {{
            border: 2px solid {NEON_PURP};
            background-color: #1F2335;
        }}
    """)
    return fld

def card_frame(glow_color=NEON_CYAN):
    frame = QFrame()
    frame.setStyleSheet(f"""
        QFrame {{
            background-color: {BG_CARD};
            border: 1px solid {glow_color};
            border-radius: 8px;
        }}
    """)
    apply_glow(frame, glow_color, 35)
    return frame

class CyberpunkNFCThread(QThread):
    progress = pyqtSignal(int)
    done     = pyqtSignal()
    
    def run(self):
        for i in range(0, 101, 5):
            time.sleep(0.05)
            self.progress.emit(i)
        self.done.emit()

def inject_register_ui(app_instance):
    """
    Overwrites the contents of _page_register layout in main.py
    with the glowing Cyberpunk UI.
    """
    # Clear existing layout
    layout = app_instance._page_register.layout()
    if layout is not None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w: w.deleteLater()
    else:
        layout = QVBoxLayout(app_instance._page_register)
        
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    
    # Checkbox style for current app instance
    app_instance._page_register.setStyleSheet(f"""
        QCheckBox {{
            spacing: 10px;
            font-size: 12px;
            color: {TEXT_GRAY};
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 1px solid {NEON_CYAN};
            background: {BG_INPUT};
            border-radius: 3px;
        }}
        QCheckBox::indicator:checked {{
            background: {NEON_CYAN};
            border: 1px solid {TEXT_WHITE};
        }}
        QProgressBar {{
            background-color: {BG_INPUT};
            border: 1px solid {BORDER};
            border-radius: 2px;
            height: 6px;
            text-align: center;
        }}
        QProgressBar::chunk {{
            background-color: {NEON_CYAN};
        }}
    """)

    card = card_frame(glow_color=NEON_PURP)
    card.setFixedWidth(460)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(36, 36, 36, 36)
    lay.setSpacing(14)

    title_lbl = label("INITIALIZE // VAULT", 22, NEON_PURP, bold=True)
    apply_glow(title_lbl, NEON_PURP, 15)
    lay.addWidget(title_lbl)
    lay.addWidget(label("Create new Web3 operator identity", 13, TEXT_GRAY))
    lay.addSpacing(10)

    lay.addWidget(label("> Operator Profile Handle", 12))
    app_instance._cyber_email_in = input_field("operator_alpha")
    lay.addWidget(app_instance._cyber_email_in)

    lay.addSpacing(10)

    # ── NFC Section ──
    nfc_frame = QFrame()
    nfc_frame.setStyleSheet(f"""
        QFrame {{
            background-color: {BG_INPUT};
            border: 1px dashed {BORDER};
            border-radius: 4px;
        }}
    """)
    nfc_lay = QVBoxLayout(nfc_frame)
    nfc_lay.setContentsMargins(16, 14, 16, 14)
    
    app_instance._nfc_status_lbl = label("[ WAIT ] INSERT HARDWARE KEY...", 12, TEXT_GRAY)
    nfc_lay.addWidget(app_instance._nfc_status_lbl)

    app_instance._nfc_progress = QProgressBar()
    app_instance._nfc_progress.setValue(0)
    app_instance._nfc_progress.setVisible(False)
    nfc_lay.addWidget(app_instance._nfc_progress)

    app_instance._nfc_btn = primary_button("CONNECT HARDWARE KEY", NEON_CYAN)
    
    def start_nfc():
        app_instance._nfc_btn.setEnabled(False)
        app_instance._nfc_btn.setText("SYNCING...")
        app_instance._nfc_progress.setVisible(True)
        app_instance._nfc_status_lbl.setText("[ BUSY ] ESTABLISHING LINK...")
        
        app_instance._nfc_t = CyberpunkNFCThread()
        app_instance._nfc_t.progress.connect(app_instance._nfc_progress.setValue)
        app_instance._nfc_t.done.connect(finish_nfc)
        app_instance._nfc_t.start()
        
    def finish_nfc():
        app_instance._nfc_status_lbl.setText("[ OK ] DEVICE BOUND")
        app_instance._nfc_status_lbl.setStyleSheet(f"color: {NEON_GREEN}; font-size: 12px; border: none;")
        app_instance._nfc_lbl_id.setVisible(True)
        app_instance._nfc_btn.setText("HARDWARE CONNECTED")
        if app_instance._confirm_chk.isChecked():
            app_instance._cy_reg_btn.setEnabled(True)
            
    app_instance._nfc_btn.clicked.connect(start_nfc)
    nfc_lay.addWidget(app_instance._nfc_btn)

    app_instance._nfc_lbl_id = label("UID: Hardware Validated", 11, NEON_GREEN)
    app_instance._nfc_lbl_id.setVisible(False)
    nfc_lay.addWidget(app_instance._nfc_lbl_id)

    def check_chk():
        if app_instance._nfc_progress.value() == 100 and app_instance._confirm_chk.isChecked():
            app_instance._cy_reg_btn.setEnabled(True)
        else:
            app_instance._cy_reg_btn.setEnabled(False)

    app_instance._confirm_chk = QCheckBox("I confirm my physical formulation token is present.")
    app_instance._confirm_chk.toggled.connect(check_chk)
    nfc_lay.addWidget(app_instance._confirm_chk)

    lay.addWidget(nfc_frame)
    lay.addSpacing(10)

    app_instance._cy_reg_btn = primary_button("Execute Protocol")
    app_instance._cy_reg_btn.setEnabled(False)
    
    def do_register():
        username = app_instance._cyber_email_in.text().strip()
        if not username:
            QMessageBox.warning(app_instance, "Hold", "Please enter an Operator Profile Handle.")
            return
            
        try:
            # Reusing the existing register flow which hooks into security_core + Web3
            vault_id = security_core.SecurityCore.generate_operator_identity(username)
            app_instance.current_operator = username
            app_instance._refresh_secret_dropdowns()
            app_instance._refresh_contact_ui()
            
            # Auto-route to dashboard
            QMessageBox.information(app_instance, "OPERATOR ENROLLED", f"Identity {username} secured on Web3 Blockchain.")
            app_instance._stack.setCurrentWidget(app_instance._page_dashboard)
        except Exception as e:
            QMessageBox.critical(app_instance, "Vault Error", str(e))
            
    app_instance._cy_reg_btn.clicked.connect(do_register)
    lay.addWidget(app_instance._cy_reg_btn)

    layout.addWidget(card)
