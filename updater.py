import json
import logging
import os
import subprocess
import urllib.request
import signal
from pathlib import Path
from PyQt6.QtWidgets import QMessageBox

logger = logging.getLogger(__name__)

GITHUB_REPO = "adarshnarainshukla/ANSxVault" # Replace with actual when created
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
CURRENT_VERSION = "v1.0.0"

class OTAUpdater:
    @staticmethod
    def check_for_updates(parent_widget=None):
        logger.info(f"[OTA] Checking for updates online. Current: {CURRENT_VERSION}")
        try:
            req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github.v3+json"})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                latest_version = data.get("tag_name", CURRENT_VERSION)
                
                if latest_version > CURRENT_VERSION:
                    logger.info(f"[OTA] New version found: {latest_version}")
                    
                    # Find DMG asset
                    dmg_url = None
                    for asset in data.get("assets", []):
                        if asset.get("name", "").endswith(".dmg"):
                            dmg_url = asset.get("browser_download_url")
                            break
                            
                    if dmg_url and parent_widget:
                        reply = QMessageBox.question(
                            parent_widget,
                            "System Update Available",
                            f"A core cryptographic update ({latest_version}) was intercepted.\n\n"
                            "Do you wish to initiate OTA replacement sequence?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )
                        if reply == QMessageBox.StandardButton.Yes:
                            OTAUpdater.perform_update_sequence(dmg_url, latest_version)
                            
        except Exception as e:
            logger.warning(f"[OTA] Update check bypassed (Offline or Error): {e}")

    @staticmethod
    def perform_update_sequence(dmg_url: str, version: str):
        """Silently downloads and triggers the swap."""
        logger.info("[OTA] Initiating Download Sequence...")
        download_path = f"/tmp/ANSxVault_{version}.dmg"
        
        try:
            urllib.request.urlretrieve(dmg_url, download_path)
            logger.info("[OTA] Payload acquired. Initiating Swap Protocol.")
            
            # Bash script to mount DMG, copy .app, and restart
            # This is intentionally detached so it survives the app closing.
            swap_script = f'''#!/bin/bash
            sleep 2
            hdiutil attach "{download_path}" -mountpoint /Volumes/ANSxUpdater -nobrowse -quiet
            if [ -d "/Applications/ANSx Vault.app" ]; then
                rm -rf "/Applications/ANSx Vault.app"
            fi
            cp -R "/Volumes/ANSxUpdater/ANSx Vault.app" /Applications/
            hdiutil detach /Volumes/ANSxUpdater -quiet
            rm "{download_path}"
            open "/Applications/ANSx Vault.app"
            '''
            
            script_path = "/tmp/ansx_ota_swap.sh"
            with open(script_path, "w") as f:
                f.write(swap_script)
            os.chmod(script_path, 0o755)
            
            subprocess.Popen([script_path], start_new_session=True)
            
            # Suicide pill
            logger.warning("[OTA] Update triggered. Terminating current instance.")
            os.kill(os.getpid(), signal.SIGTERM)
            
        except Exception as e:
            logger.error(f"[OTA] Update Sequence FATAL: {e}")
