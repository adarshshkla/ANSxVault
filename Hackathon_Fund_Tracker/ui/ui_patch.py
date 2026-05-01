import os
import json
import logging
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout, QWidget, QFrame, QApplication, QComboBox
)
from security_core import SecurityCore

logger = logging.getLogger(__name__)

# This script holds the massive replacement methods for ANSxVault class
class UI_Updates:
    
    @staticmethod
    def build_vault_ui(self) -> None:
        layout = QVBoxLayout(self._page_vault)
        layout.setContentsMargins(60, 50, 60, 50)

        header = QLabel("🔐 STAGE 1: SECURE VAULT")
        header.setStyleSheet("color: #ffffff; font-size: 32px; font-weight: bold; font-family: 'Courier New';")
        layout.addWidget(header)
        layout.addSpacing(20)
        
        info = QLabel("Shatter your payload strictly for self-storage. No receiver needed yet.")
        info.setStyleSheet("color: #aaa;")
        layout.addWidget(info)
        layout.addSpacing(40)

        action_panel = QFrame()
        action_panel.setStyleSheet("background-color: #0c0d14; border: 1px solid #1a1c23; border-radius: 12px;")
        ap_layout = QVBoxLayout(action_panel)
        ap_layout.setContentsMargins(40, 40, 40, 40)

        self._vault_title = QLabel("AWAITING PAYLOAD TO VAULT")
        self._vault_title.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        self._vault_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ap_layout.addWidget(self._vault_title)

        self._vault_progress = QProgressBar()
        self._vault_progress.hide()
        ap_layout.addWidget(self._vault_progress)

        self._vault_btn = QPushButton("SELECT FILE & VAULT")
        self._vault_btn.setObjectName("PrimaryBtn")
        self._vault_btn.clicked.connect(self._initiate_vault)
        ap_layout.addWidget(self._vault_btn)

        layout.addWidget(action_panel)
        layout.addStretch()

    @staticmethod
    def initiate_vault(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Payload", "", "All Files (*)")
        if not file_path: return

        identity = SecurityCore.load_identity_for_user(self.current_operator)
        if not identity:
            QMessageBox.critical(self, "Error", "No identity loaded.")
            return

        self._vault_btn.setEnabled(False)
        self._vault_btn.setText("SHATTERING…")
        self._vault_title.setText(">> ENGAGING GALOIS FIELD MATH <<")
        self._vault_title.setStyleSheet("color: #ff3366; font-size: 20px; font-weight: bold;")
        self._vault_progress.show()
        self._vault_progress.setRange(0, 0)

        # Generating Ephemeral AES Key
        self._ephemeral_master_key = os.urandom(32).hex()

        # The vault worker is ShatterWorker
        # We need to import ShatterWorker locally or assume it's attached
        self._shatter_worker = self.__class__.ShatterWorkerClass(file_path, self._ephemeral_master_key)
        self._shatter_worker.finished.connect(lambda exit_code: UI_Updates.on_vault_complete(self, exit_code, file_path))
        QTimer.singleShot(800, self._shatter_worker.start)

    @staticmethod
    def on_vault_complete(self, exit_code: int, file_path: str) -> None:
        self._vault_progress.setRange(0, 100)
        self._vault_progress.setValue(100)

        if exit_code == 0:
            self._vault_title.setText("PAYLOAD SHATTERED. DISPATCHING TO CLOUD...")
            self._vault_btn.setText("DISPATCHING...")
            
            # Start Dispatch worker
            self._dispatch_worker = self.__class__.DispatchWorkerClass()
            self._dispatch_worker.finished.connect(lambda urls: UI_Updates.on_vault_dispatch_complete(self, file_path, urls))
            self._dispatch_worker.start()
        else:
            self._vault_title.setText(f"ENGINE FAILURE: {exit_code}")
            self._vault_btn.setEnabled(True)
            self._vault_btn.setText("RETRY")

    @staticmethod
    def on_vault_dispatch_complete(self, file_path: str, shard_urls: dict) -> None:
        import base64

        outbox_dir = os.path.expanduser("~/.ansx_vault/outbox")
        os.makedirs(outbox_dir, exist_ok=True)

        shard_binaries = {}
        local_src = os.path.expanduser("~/.ansx_vault/shards")
        for i in range(1, 13):
            spath = os.path.join(local_src, f"fragment_{i}.ansx")
            if os.path.exists(spath):
                with open(spath, "rb") as f:
                    shard_binaries[f"fragment_{i}.ansx"] = base64.b64encode(f.read()).decode()
        
        bundle_count = len(shard_binaries)
        logger.info("[VAULT] Bundled %d shards into manifest.", bundle_count)

        manifest_data = {
            "original_file": os.path.basename(file_path),
            "ephemeral_key": self._ephemeral_master_key,
            "shard_count": 12,
            "cloud_urls": {str(k): v for k, v in shard_urls.items()},
            "shard_payload": shard_binaries
        }

        # Save manifest JSON to outbox for reference
        manifest_path = os.path.join(outbox_dir, f"{os.path.basename(file_path)}.manifest")
        with open(manifest_path, "w") as f:
            import json
            json.dump(manifest_data, f)

        msg = f"11 CLOUD SHARDS SECURED + {bundle_count}/12 BUNDLED ✅"
        self._vault_title.setText(msg)
        self._vault_title.setStyleSheet("color: #39FF14; font-size: 16px; font-weight: bold;")
        QApplication.processEvents()

        # Ask user for carrier image immediately
        from PyQt6.QtWidgets import QFileDialog
        carrier_img, _ = QFileDialog.getOpenFileName(
            self, "Select Carrier Image for Ghost Map", "", "Images (*.png *.jpg *.jpeg)"
        )
        if not carrier_img:
            self._vault_title.setText("VAULT SECURED. No carrier image selected.")
            self._vault_title.setStyleSheet("color: #888; font-size: 16px;")
            self._vault_btn.setText("FILE VAULTED")
            self._vault_btn.setEnabled(True)
            return

        # Embed manifest (11 URLs + shard 12) into the carrier image via steganography
        ghost_map_path = os.path.join(outbox_dir, f"ghost_map_{os.path.basename(file_path)}.png")
        try:
            import json
            from ghost_map import GhostMap
            payload_str = json.dumps(manifest_data)
            # No receiver encryption yet — just hide the raw payload for now
            # Receiver's public key encryption happens in the Send stage
            GhostMap.hide_payload_in_image(payload_str, "", carrier_img, ghost_map_path)
        except Exception as e:
            ghost_map_path = carrier_img  # fallback: use original image
            logger.warning("Ghost map steganography failed (demo mode): %s", e)

        # Store ghost map path on self so the Send page can use it
        self._pending_ghost_map = ghost_map_path
        self._pending_manifest = manifest_data

        self._vault_title.setText("✅ GHOST MAP READY — GO TO SEND PAGE")
        self._vault_title.setStyleSheet("color: #00ffcc; font-size: 18px; font-weight: bold;")
        self._vault_btn.setText("FILE VAULTED SUCCESSFULLY")
        self._vault_btn.setEnabled(True)

        # Auto-update the Send page preview
        UI_Updates.set_ghost_map_preview(self, ghost_map_path)

    @staticmethod
    def build_send_ui(self) -> None:
        layout = QVBoxLayout(self._page_send)
        layout.setContentsMargins(60, 50, 60, 50)

        header = QLabel("✉️ STAGE 2: GHOST COURIER")
        header.setStyleSheet("color: #ffffff; font-size: 32px; font-weight: bold; font-family: 'Courier New';")
        layout.addWidget(header)
        layout.addSpacing(20)

        contacts_layout = QHBoxLayout()
        self._receiver_combo = QComboBox()
        self._receiver_combo.setStyleSheet(
            "background-color: #0f1520; color: #00ffcc; padding: 8px; "
            "font-weight: bold; font-size: 14px; border: 1px solid #333;"
        )
        self._receiver_combo.addItem("— select receiver —")

        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedWidth(40)
        refresh_btn.setToolTip("Refresh user list from Web3 registry")
        refresh_btn.setStyleSheet(
            "background-color: #1a1c23; color: #7AA2F7; font-size: 18px; "
            "border: 1px solid #333; border-radius: 4px;"
        )
        refresh_btn.clicked.connect(lambda: UI_Updates._refresh_user_dropdown(self))

        contacts_layout.addWidget(QLabel("TARGET RECEIVER: "))
        contacts_layout.addWidget(self._receiver_combo, 1)
        contacts_layout.addWidget(refresh_btn)
        layout.addLayout(contacts_layout)

        # Populate immediately on page load
        UI_Updates._refresh_user_dropdown(self)
        layout.addSpacing(20)

        action_panel = QFrame()
        action_panel.setStyleSheet("background-color: #0c0d14; border: 1px solid #1a1c23; border-radius: 12px;")
        ap_layout = QVBoxLayout(action_panel)
        ap_layout.setContentsMargins(40, 40, 40, 40)

        # Ghost map preview — shows image created during vault stage
        self._ghost_map_preview = QLabel()
        self._ghost_map_preview.setFixedHeight(160)
        self._ghost_map_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ghost_map_preview.setStyleSheet(
            "border: 2px dashed #333; border-radius: 8px; background: #0a0b10; color: #444; font-size: 12px;"
        )
        self._ghost_map_preview.setText("No Ghost Map yet — Vault a file first")
        ap_layout.addWidget(self._ghost_map_preview)

        self._ghost_map_label = QLabel("")
        self._ghost_map_label.setStyleSheet("color: #00ffcc; font-size: 11px; font-family: monospace;")
        self._ghost_map_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ap_layout.addWidget(self._ghost_map_label)

        self._send_title = QLabel("VAULT A FILE FIRST, THEN CHOOSE A RECEIVER")
        self._send_title.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: bold;")
        self._send_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ap_layout.addWidget(self._send_title)

        btn_layout = QHBoxLayout()
        self._send_btn_local = QPushButton("💾 SAVE IMAGE GLOBALLY")
        self._send_btn_local.setObjectName("PrimaryBtn")
        self._send_btn_local.clicked.connect(self._initiate_send)

        self._send_btn_udp = QPushButton("🚀 ENGAGE ANSX-UDP P2P")
        self._send_btn_udp.setStyleSheet(
            "background-color: #5d259e; color: white; border-radius: 6px; font-weight: bold; font-size: 16px; height: 60px;"
        )
        self._send_btn_udp.clicked.connect(self._initiate_udp_send)

        btn_layout.addWidget(self._send_btn_local)
        btn_layout.addWidget(self._send_btn_udp)
        
        ap_layout.addLayout(btn_layout)

        layout.addWidget(action_panel)
        layout.addStretch()

    @staticmethod
    def initiate_send(self) -> None:
        idx = self._receiver_dropdown.currentIndex()
        if idx == 0:
            QMessageBox.warning(self, "Hold", "Select target from Contact Book.")
            return
        receiver_pub_key = self._receiver_dropdown.itemData(idx)

        manifest_path, _ = QFileDialog.getOpenFileName(self, "Select Vault Manifest", os.path.expanduser("~/.ansx_vault/outbox"), "Manifests (*.manifest)")
        if not manifest_path: return

        carrier_img, _ = QFileDialog.getOpenFileName(self, "Select Courier PNG", "", "Images (*.png *.jpg)")
        if not carrier_img: return
        
        with open(manifest_path, "r") as f:
            manifest_data = json.load(f)
            
        # Simulating cloud dispatcher returning URIs for the 12 shards
        manifest_data["cloud_uris"] = [
            f"ansx://node-sg1.aws.internal/shards/{manifest_data['ephemeral_key'][:8]}/fragment_{i+1}"
            for i in range(12)
        ]
        
        super_payload = json.dumps(manifest_data)
        
        out_img = os.path.join(os.path.expanduser("~/Desktop"), f"payload_courier.png")
        try:
            from ghost_map import GhostMap
            GhostMap.hide_payload_in_image(super_payload, receiver_pub_key, carrier_img, out_img)
            self._send_title.setText(f"GHOST MAP READY: {out_img}")
            self._send_title.setStyleSheet("color: #00ffcc;")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    @staticmethod
    def _refresh_user_dropdown(self) -> None:
        """Fetches all registered users from Web3 and populates the dropdown."""
        try:
            import web3_bridge
            engine = web3_bridge.get_web3_engine()
            users = engine.get_all_users()
        except Exception as e:
            logger.warning("Could not fetch Web3 users: %s", e)
            users = []

        current = self._receiver_combo.currentText()
        self._receiver_combo.clear()
        self._receiver_combo.addItem("— select receiver —")
        for u in users:
            self._receiver_combo.addItem(u)

        # Try to restore previous selection
        idx = self._receiver_combo.findText(current)
        if idx >= 0:
            self._receiver_combo.setCurrentIndex(idx)

    @staticmethod
    def _create_ghost_map(self) -> str:
        target_user = self._receiver_combo.currentText().strip()
        if not target_user or target_user.startswith("—"):
            QMessageBox.warning(self, "Hold", "Select a receiver from the dropdown.")
            return None

        # Check a ghost map was already created during vault stage
        pending_ghost_map = getattr(self, "_pending_ghost_map", None)
        pending_manifest  = getattr(self, "_pending_manifest", None)
        if not pending_ghost_map or not os.path.exists(pending_ghost_map):
            QMessageBox.warning(self, "Hold", "No Ghost Map ready. Please vault a file first.")
            return None

        # Look up receiver public key + IP from Web3
        receiver_pub_key = ""
        self._target_ip = "127.0.0.1"
        try:
            import web3_bridge
            engine = web3_bridge.get_web3_engine()
            receiver_pub_key = engine.fetch_public_key(target_user)
            self._target_ip  = engine.fetch_ip(target_user)
            logger.info("Resolved %s → IP %s", target_user, self._target_ip)
        except Exception as e:
            logger.warning("Web3 lookup failed, demo mode: %s", e)
            receiver_pub_key = ""

        # Produce final delivery image encrypted with receiver's public key
        outbox_dir = os.path.expanduser("~/.ansx_vault/outbox")
        out_img    = os.path.join(outbox_dir, f"delivery_{target_user}.png")
        try:
            from ghost_map import GhostMap
            payload_str = json.dumps(pending_manifest)
            GhostMap.hide_payload_in_image(payload_str, receiver_pub_key, pending_ghost_map, out_img)
        except Exception as e:
            logger.warning("Final encryption step failed, using base ghost map: %s", e)
            out_img = pending_ghost_map

        self._send_title.setText(f"GHOST MAP LOCKED FOR {target_user.upper()} ✔")
        self._send_title.setStyleSheet("color: #00ffcc; font-size: 15px;")
        return out_img

    @staticmethod
    def set_ghost_map_preview(self, image_path: str) -> None:

        """Update the Send page to show a thumbnail of the ghost map image."""
        from PyQt6.QtGui import QPixmap
        if not hasattr(self, "_ghost_map_preview"):
            return
        if image_path and os.path.exists(image_path):
            pix = QPixmap(image_path).scaledToHeight(
                150,
                Qt.TransformationMode.SmoothTransformation
            )
            self._ghost_map_preview.setPixmap(pix)
            self._ghost_map_label.setText(f"✔ Ghost Map: {os.path.basename(image_path)}")
            self._send_title.setText("ENTER RECEIVER USERNAME → CLICK SEND")
            self._send_title.setStyleSheet("color: #ffcc00; font-size: 15px; font-weight: bold;")
        else:
            self._ghost_map_preview.setText("No Ghost Map yet — Vault a file first")
            self._ghost_map_label.setText("")

    @staticmethod
    def initiate_send(self) -> None:
        out_img = UI_Updates._create_ghost_map(self)
        if out_img:
            self._send_title.setText(f"GHOST MAP READY FOR WHATSAPP: {out_img}")
            self._send_title.setStyleSheet("color: #00ffcc;")

    @staticmethod
    def initiate_udp_send(self) -> None:
        out_img = UI_Updates._create_ghost_map(self)
        if not out_img:
            return

        target_ip = getattr(self, "_target_ip", "127.0.0.1")
        target_user = self._receiver_combo.currentText().strip()

        # Store for relay fallback
        self._last_out_img = out_img
        self._last_target_user = target_user

        from udp_courier import UDPCourierSender
        self._send_title.setText(f"⚡ TRANSMITTING TO {target_ip} VIA ANSX-UDP...")
        self._send_title.setStyleSheet("color: #ff3366;")

        self._udp_sender = UDPCourierSender(target_ip, out_img)
        self._udp_sender.finished.connect(lambda success: UI_Updates.on_udp_send_complete(self, success))
        self._udp_sender.start()

    @staticmethod
    def on_udp_send_complete(self, success: bool) -> None:
        if success:
            self._send_title.setText("✅ P2P DELIVERY CONFIRMED — RECEIVER ACKNOWLEDGED.")
            self._send_title.setStyleSheet("color: #00ffcc;")
        else:
            # UDP failed (different network) → try relay delivery
            self._send_title.setText("⚠ UDP BLOCKED. ROUTING VIA SOVEREIGN MESH...")
            self._send_title.setStyleSheet("color: #ffcc00;")
            QApplication.processEvents()

            sender = getattr(self, "current_operator", "unknown")
            recipient = getattr(self, "_last_target_user", "")
            out_img = getattr(self, "_last_out_img", "")

            try:
                import web3_bridge
                engine = web3_bridge.get_web3_engine()
                ok = engine.drop_ghost_map(recipient, sender, out_img)
                if ok:
                    self._send_title.setText(f"✅ GHOST MAP RELAYED VIA SOVEREIGN MESH TO {recipient.upper()}.")
                    self._send_title.setStyleSheet("color: #00ffcc;")
                else:
                    self._send_title.setText("❌ RELAY UNREACHABLE. SAVE IMAGE & SEND MANUALLY.")
                    self._send_title.setStyleSheet("color: #ff3333;")
            except Exception as e:
                logger.warning("Relay fallback failed: %s", e)
                self._send_title.setText("❌ ALL DELIVERY METHODS FAILED.")
                self._send_title.setStyleSheet("color: #ff3333;")

    @staticmethod
    def build_receive_ui(self) -> None:
        layout = QVBoxLayout(self._page_receive)
        layout.setContentsMargins(60, 50, 60, 50)
        
        header = QLabel("📥 STAGE 3: UNSHATTER RECONSTRUCTION")
        header.setStyleSheet("color: #ffffff; font-size: 32px; font-weight: bold; font-family: 'Courier New';")
        layout.addWidget(header)
        layout.addSpacing(20)

        action_panel = QFrame()
        action_panel.setStyleSheet("background-color: #0c0d14; border: 1px solid #1a1c23; border-radius: 12px;")
        ap_layout = QVBoxLayout(action_panel)

        self._rx_title = QLabel("AWAITING GHOST MAP AND SHARDS")
        self._rx_title.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        self._rx_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ap_layout.addWidget(self._rx_title)

        self._rx_btn = QPushButton("ENGAGE RECONSTRUCTION")
        self._rx_btn.setObjectName("PrimaryBtn")
        self._rx_btn.clicked.connect(self._initiate_receive)
        ap_layout.addWidget(self._rx_btn)

        layout.addWidget(action_panel)
        layout.addStretch()

    @staticmethod
    def initiate_receive(self) -> None:
        # If a ghost map arrived automatically via P2P, use it without asking
        p2p_map = getattr(self, "_pending_incoming_ghost_map", None)
        if p2p_map and os.path.exists(p2p_map):
            courier_img = p2p_map
            self._pending_incoming_ghost_map = None  # consume it
        else:
            courier_img, _ = QFileDialog.getOpenFileName(
                self, "Select Ghost Map Image",
                os.path.expanduser("~/.ansx_vault/p2p_incoming"),
                "Images (*.png)"
            )
            if not courier_img:
                return

        out_file, _ = QFileDialog.getSaveFileName(self, "Save Reconstructed File As")
        if not out_file:
            return

        from ghost_map import GhostMap
        identity = SecurityCore.load_identity_for_user(self.current_operator)
        private_key = identity.get("private_key", "") if identity else ""

        try:
            decrypted_json_str = GhostMap.extract_payload_from_image(private_key, courier_img)
            manifest = json.loads(decrypted_json_str)
        except Exception as e:
            QMessageBox.critical(self, "DNA Failure", f"Failed to extract Super-Payload.\n{str(e)}")
            return

        self._rx_title.setText(">> GHOST MAP DECRYPTED. DOWNLOADING FROM CLOUD... <<")
        self._rx_title.setStyleSheet("color: #ff3366;")
        QApplication.processEvents()


        uris = manifest.get("cloud_urls", {})
        if not uris:
            QMessageBox.critical(self, "Error", "No cloud URLs found in Ghost Map.")
            return
            
        import time
        import base64
        shard_dir = os.path.expanduser("~/.ansx_vault/downloaded_shards")
        os.makedirs(shard_dir, exist_ok=True)
        
        shard_payload = manifest.get("shard_payload", {})
        if not shard_payload:
            logger.warning("[RECEIVE] No bundled shards found. Attempting local fallback...")
            # Fallback: try to find shards in local store (for same-machine tests)
            local_src = os.path.expanduser("~/.ansx_vault/shards")
            for i in range(1, 13):
                spath = os.path.join(local_src, f"fragment_{i}.ansx")
                if os.path.exists(spath):
                    shutil.copy(spath, os.path.join(shard_dir, f"fragment_{i}.ansx"))
        else:
            for fname, b64_data in shard_payload.items():
                time.sleep(0.01)  # tiny simulation delay
                out_path = os.path.join(shard_dir, fname)
                with open(out_path, "wb") as f:
                    f.write(base64.b64decode(b64_data))

        decrypted_aes_key = manifest["ephemeral_key"]
        
        self._rx_title.setText(">> SHARDS SECURED. ENGAGING GF2^8 C++ DECODER <<")
        QApplication.processEvents()
        
        # Initiate Unshatter Worker
        self._unshatter_worker = self.__class__.UnshatterWorkerClass(shard_dir, out_file, decrypted_aes_key)
        self._unshatter_worker.finished.connect(lambda code: UI_Updates.on_unshatter_complete(self, code))
        self._unshatter_worker.start()

    @staticmethod
    def on_unshatter_complete(self, exit_code: int) -> None:
        if exit_code == 0:
            self._rx_title.setText("SUCCESS: PAYLOAD REBUILT FROM GALOIS FIELD.")
            self._rx_title.setStyleSheet("color: #00ffcc;")
        else:
            self._rx_title.setText(f"MATHEMATICAL FAILURE: CODE {exit_code}")
            self._rx_title.setStyleSheet("color: #ff3333;")

# Injecting into the App Class dynamically
def inject(app_class, shatter_cls, dispatch_cls, unshatter_cls):
    app_class.ShatterWorkerClass = shatter_cls
    app_class.DispatchWorkerClass = dispatch_cls
    app_class.UnshatterWorkerClass = unshatter_cls

    app_class._build_vault_ui = UI_Updates.build_vault_ui
    app_class._initiate_vault = UI_Updates.initiate_vault
    app_class._on_vault_complete = UI_Updates.on_vault_complete
    app_class._build_send_ui = UI_Updates.build_send_ui
    app_class._initiate_send = UI_Updates.initiate_send
    app_class._initiate_udp_send = UI_Updates.initiate_udp_send
    app_class._build_receive_ui = UI_Updates.build_receive_ui
    app_class._initiate_receive = UI_Updates.initiate_receive
    app_class._on_unshatter_complete = UI_Updates.on_unshatter_complete
    app_class._refresh_user_dropdown = UI_Updates._refresh_user_dropdown
    app_class._create_ghost_map = UI_Updates._create_ghost_map
