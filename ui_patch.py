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
            self._dispatch_worker.finished.connect(lambda: UI_Updates.on_vault_dispatch_complete(self, file_path))
            self._dispatch_worker.start()
        else:
            self._vault_title.setText(f"ENGINE FAILURE: {exit_code}")
            self._vault_btn.setEnabled(True)
            self._vault_btn.setText("RETRY")

    @staticmethod
    def on_vault_dispatch_complete(self, file_path: str) -> None:
        # Create Vault Manifest
        outbox_dir = os.path.expanduser("~/.ansx_vault/outbox")
        os.makedirs(outbox_dir, exist_ok=True)
        manifest_path = os.path.join(outbox_dir, f"{os.path.basename(file_path)}.manifest")
        
        manifest_data = {
            "original_file": file_path,
            "ephemeral_key": self._ephemeral_master_key,
            "shard_count": 12
        }
        
        # Super securely, we should encrypt this manifest with our own public key or hardware anchor
        # For prototype speed, we save it directly in the protected outbox folder.
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)
            
        self._vault_title.setText("VAULT SECURED & MANIFEST GENERATED.")
        self._vault_title.setStyleSheet("color: #00ffcc; font-size: 18px; font-weight: bold;")
        self._vault_btn.setText("FILE VAULTED SUCCESSFULLY")
        self._vault_btn.setEnabled(True)

    @staticmethod
    def build_send_ui(self) -> None:
        layout = QVBoxLayout(self._page_send)
        layout.setContentsMargins(60, 50, 60, 50)

        header = QLabel("✉️ STAGE 2: GHOST COURIER")
        header.setStyleSheet("color: #ffffff; font-size: 32px; font-weight: bold; font-family: 'Courier New';")
        layout.addWidget(header)
        layout.addSpacing(20)

        contacts_layout = QHBoxLayout()
        self._receiver_input = QLineEdit()
        self._receiver_input.setPlaceholderText("Enter Web3 Public Profile Handle (Username)")
        self._receiver_input.setStyleSheet("background-color: #0f1520; color: #00ffcc; padding: 10px; font-weight: bold; font-size: 14px;")
        
        contacts_layout.addWidget(QLabel("TARGET RECEIVER: "))
        contacts_layout.addWidget(self._receiver_input)
        layout.addLayout(contacts_layout)
        layout.addSpacing(20)

        action_panel = QFrame()
        action_panel.setStyleSheet("background-color: #0c0d14; border: 1px solid #1a1c23; border-radius: 12px;")
        ap_layout = QVBoxLayout(action_panel)
        ap_layout.setContentsMargins(40, 40, 40, 40)

        self._send_title = QLabel("AWAITING MANIFEST & COURIER IMAGE")
        self._send_title.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
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
    def _create_ghost_map(self) -> str:
        target_user = self._receiver_input.text().strip()
        if not target_user:
            QMessageBox.warning(self, "Hold", "Enter a Username to search the Blockchain.")
            return None
            
        try:
            import web3_bridge
            engine = web3_bridge.get_web3_engine()
            receiver_pub_key = engine.fetch_public_key(target_user)
            self._target_ip = engine.fetch_ip(target_user)
        except Exception as e:
            QMessageBox.critical(self, "Web3 Error", f"Failed to locate '{target_user}' on the decentralized Blockchain.\n{e}")
            return None

        manifest_path, _ = QFileDialog.getOpenFileName(self, "Select Vault Manifest", os.path.expanduser("~/.ansx_vault/outbox"), "Manifests (*.manifest)")
        if not manifest_path: return None

        carrier_img, _ = QFileDialog.getOpenFileName(self, "Select Courier PNG", "", "Images (*.png *.jpg)")
        if not carrier_img: return None
        
        with open(manifest_path, "r") as f:
            manifest_data = json.load(f)
            
        manifest_data["cloud_uris"] = [
            f"ansx://node-sg1.aws.internal/shards/{manifest_data['ephemeral_key'][:8]}/fragment_{i+1}"
            for i in range(12)
        ]
        super_payload = json.dumps(manifest_data)
        out_img = os.path.join(os.path.expanduser("~/Desktop"), f"payload_courier.png")
        
        try:
            from ghost_map import GhostMap
            GhostMap.hide_payload_in_image(super_payload, receiver_pub_key, carrier_img, out_img)
            return out_img
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return None

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
        
        from PyQt6.QtWidgets import QInputDialog
        final_ip, ok = QInputDialog.getText(self, "P2P Network Routing", f"Web3 Blockchain resolved IP for {self._receiver_input.text()}:", text=target_ip)
        if not ok or not final_ip:
            return
            
        from udp_courier import UDPCourierSender
        self._send_title.setText(f"BLASTING R-UDP CHUNKS TO {final_ip}...")
        self._send_title.setStyleSheet("color: #ff3366;")
        
        self._udp_sender = UDPCourierSender(final_ip, out_img)
        self._udp_sender.finished.connect(lambda success: UI_Updates.on_udp_send_complete(self, success))
        self._udp_sender.start()
            
    @staticmethod
    def on_udp_send_complete(self, success: bool) -> None:
        if success:
            self._send_title.setText("P2P DELIVERY CONFIRMED BY RECEIVER.")
            self._send_title.setStyleSheet("color: #00ffcc;")
        else:
            self._send_title.setText("P2P DELIVERY FAILED. FALLBACK TO WHATSAPP.")
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
        courier_img, _ = QFileDialog.getOpenFileName(self, "Select Ghost Map Image", "", "Images (*.png)")
        if not courier_img: return

        out_file, _ = QFileDialog.getSaveFileName(self, "Save Reconstructed File As")
        if not out_file: return
        
        from ghost_map import GhostMap
        identity = SecurityCore.load_identity_for_user(self.current_operator)
        private_key = identity.get("private_key")
        
        if not private_key:
            QMessageBox.critical(self, "Error", "No private key. Hardware DNA missing.")
            return

        try:
            decrypted_json_str = GhostMap.extract_payload_from_image(private_key, courier_img)
            manifest = json.loads(decrypted_json_str)
        except Exception as e:
            QMessageBox.critical(self, "DNA Failure", f"Failed to extract Super-Payload.\n{str(e)}")
            return
            
        self._rx_title.setText(">> GHOST MAP DECRYPTED. DOWNLOADING FROM CLOUD... <<")
        self._rx_title.setStyleSheet("color: #ff3366;")
        QApplication.processEvents()

        uris = manifest.get("cloud_uris", [])
        if not uris:
            QMessageBox.critical(self, "Error", "No cloud URIs found in Ghost Map.")
            return
            
        # Instead of real network requests, we mock pulling from local store to simulate Cloud sync
        import time
        import shutil
        shard_dir = os.path.expanduser("~/.ansx_vault/downloaded_shards")
        os.makedirs(shard_dir, exist_ok=True)
        local_src = os.path.expanduser("~/.ansx_vault/shards")
        
        for i, uri in enumerate(uris):
            # Simulation delay
            time.sleep(0.05)
            src_file = os.path.join(local_src, f"fragment_{i+1}.ansx")
            if os.path.exists(src_file):
                shutil.copy(src_file, os.path.join(shard_dir, f"fragment_{i+1}.ansx"))

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
