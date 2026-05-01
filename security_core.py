import os
import json
import uuid
import hashlib
import hmac
import stat
import logging
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from typing import Optional

logger = logging.getLogger(__name__)

# Root directory for the entire vault system
BASE_DIR = os.path.expanduser("~/.ansx_vault")
IDENTITY_DIR = os.path.join(BASE_DIR, "identities")

# ─── Constants ──────────────────────────────────────────────────────────────
_RSA_KEY_SIZE   = 4096
_RSA_PUBLIC_EXP = 65537
_PBKDF2_ITER    = 600_000   # NIST recommended minimum for SHA-256


class SecurityCore:

    @staticmethod
    def initialize_system() -> None:
        """Creates the vault directory tree with strict 700 permissions."""
        os.makedirs(IDENTITY_DIR, mode=0o700, exist_ok=True)
        # Harden existing dirs in case they were created with loose perms
        for d in (BASE_DIR, IDENTITY_DIR):
            os.chmod(d, stat.S_IRWXU)

    @staticmethod
    def get_machine_id() -> str:
        """
        Returns a stable, hardware-derived machine identifier.
        Uses IOPlatformUUID on macOS for a more robust anchor than uuid.getnode()
        (which can change if the MAC address changes).
        Falls back to uuid.getnode() on other platforms.
        """
        try:
            import subprocess
            result = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                timeout=3,
                stderr=subprocess.DEVNULL,
            ).decode()
            for line in result.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        except Exception:
            pass
        return str(uuid.getnode())

    @staticmethod
    def get_geolocation() -> str:
        """
        Fetches the current geospatial coordinates (Latitude/Longitude).
        Uses a free IP-based API (ip-api.com) for the prototype.
        Rounds to 1 decimal place (~11km radius) to tolerate minor IP shifts,
        creating a 'Safe Zone' geofence.
        """
        try:
            import urllib.request
            import json
            req = urllib.request.Request("http://ip-api.com/json/", headers={'User-Agent': 'Mozilla'})
            with urllib.request.urlopen(req, timeout=3) as response:
                data = json.loads(response.read().decode())
                if data.get("status") == "success":
                    lat = round(float(data.get("lat", 0.0)), 1)
                    lon = round(float(data.get("lon", 0.0)), 1)
                    return f"{lat},{lon}"
        except Exception as e:
            logger.warning("Failed to fetch geolocation: %s", e)
        return "0.0,0.0"

    @classmethod
    def _derive_anchor(cls, nfc_seed: str, geolocation: str = None) -> str:
        """
        Derives the hardware anchor using PBKDF2-HMAC-SHA256 instead of a
        single raw SHA-256 pass, making the anchor resistant to brute-force.
        The Machine ID AND the Geospatial Coordinates are entangled as the salt.
        """
        if geolocation is None:
            geolocation = cls.get_geolocation()
            
        machine_id = cls.get_machine_id()
        
        # PHYSICAL ENTANGLEMENT: The math now requires the device to be
        # in the exact same physical coordinates as when it was registered.
        entangled_salt = f"{machine_id}::{geolocation}".encode()
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=entangled_salt,
            iterations=_PBKDF2_ITER,
        )
        return kdf.derive(nfc_seed.encode()).hex()

    @classmethod
    def list_registered_users(cls) -> list[str]:
        """Returns all hardware-bound operator names on this machine."""
        cls.initialize_system()
        return [
            f.removesuffix(".json")
            for f in os.listdir(IDENTITY_DIR)
            if f.endswith(".json")
        ]

    @classmethod
    def establish_identity(cls, operator_name: str, nfc_seed: str) -> str:
        """
        Binds the operator's NFC tag + machine ID into a single PBKDF2 anchor,
        then generates an RSA-4096 identity key-pair.
        Returns the new vault ID.
        """
        cls.initialize_system()

        hardware_anchor = cls._derive_anchor(nfc_seed)

        # Generate RSA-4096 identity
        private_key = rsa.generate_private_key(
            public_exponent=_RSA_PUBLIC_EXP,
            key_size=_RSA_KEY_SIZE,
        )
        pem_private = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pem_public = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        vault_id = f"ANSX-{os.urandom(6).hex().upper()}"
        identity_data = {
            "operator": operator_name,
            "hardware_anchor": hardware_anchor,
            "public_key": pem_public.decode("utf-8"),
            "private_key": pem_private.decode("utf-8"),
            "machine_id": cls.get_machine_id(),
            "vault_id": vault_id,
        }

        filepath = os.path.join(IDENTITY_DIR, f"{operator_name}.json")
        # Write atomically: write to temp file then rename
        tmp_path = filepath + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(identity_data, f, indent=4)
            # Restrict private-key file to owner-read-only before rename
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp_path, filepath)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

        # Publish directly to Web3 Decentralized PKI!
        try:
            import web3_bridge
            import socket
            # Auto-detect this machine's LAN IP for P2P routing
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
            except Exception:
                local_ip = "127.0.0.1"

            engine = web3_bridge.get_web3_engine()
            engine.register_identity(operator_name, pem_public.decode("utf-8"), local_ip)
            logger.info("Web3: Identity '%s' registered at IP %s.", operator_name, local_ip)
        except Exception as e:
            logger.error("Web3 Registration Failed: %s", e)
            raise RuntimeError(f"Blockchain Identity Conflict: {e}")

        logger.info("Identity established for operator '%s' (vault_id=%s)", operator_name, vault_id)
        return vault_id

    @classmethod
    def load_identity_for_user(cls, operator_name: str) -> Optional[dict]:
        """Retrieves the identity block for a logged-in operator."""
        if not operator_name:
            return None
        filepath = os.path.join(IDENTITY_DIR, f"{operator_name}.json")
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r") as f:
            return json.load(f)

    @classmethod
    def delete_identity(cls, operator_name: str) -> bool:
        """Deletes the identity block for the operator, wiping them from the device."""
        if not operator_name:
            return False
        filepath = os.path.join(IDENTITY_DIR, f"{operator_name}.json")
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info("Identity '%s' wiped from device.", operator_name)
                return True
        except Exception as e:
            logger.error("Failed to delete identity '%s': %s", operator_name, e)
        return False

    @classmethod
    def verify_login(cls, operator_name: str, nfc_seed: str) -> bool:
        """
        Verifies that the NFC tag matches the stored machine-bound anchor.
        Uses hmac.compare_digest to prevent timing-oracle attacks.
        """
        data = cls.load_identity_for_user(operator_name)
        if not data:
            return False

        check_anchor = cls._derive_anchor(nfc_seed)
        stored_anchor = data.get("hardware_anchor", "")
        # Constant-time comparison
        return hmac.compare_digest(check_anchor, stored_anchor)

    # ─── CONTACT BOOK (PUBLIC KEY EXCHANGE) ─────────────────────────────────

    @classmethod
    def export_public_identity(cls, operator_name: str, target_dir: str) -> str:
        """
        Exports only the Public Key of the operator into a .ansx_id file.
        Contains absolutely no secret material. Safe to email.
        """
        data = cls.load_identity_for_user(operator_name)
        if not data:
            raise ValueError(f"Operator {operator_name} not found.")

        export_data = {
            "operator": data["operator"],
            "public_key": data["public_key"]
        }

        os.makedirs(target_dir, exist_ok=True)
        export_path = os.path.join(target_dir, f"{operator_name}.ansx_id")
        with open(export_path, "w") as f:
            json.dump(export_data, f, indent=4)
        
        return export_path

    @classmethod
    def import_contact(cls, ansx_id_path: str) -> str:
        """
        Imports a receiver's .ansx_id file into the vault's Contact Book.
        """
        if not os.path.exists(ansx_id_path):
            raise FileNotFoundError("ID file not found.")

        with open(ansx_id_path, "r") as f:
            data = json.load(f)

        if "operator" not in data or "public_key" not in data:
            raise ValueError("Invalid .ansx_id file format.")

        contacts_dir = os.path.join(BASE_DIR, "contacts")
        os.makedirs(contacts_dir, mode=0o700, exist_ok=True)

        target_path = os.path.join(contacts_dir, f"{data['operator']}.json")
        with open(target_path, "w") as f:
            json.dump(data, f, indent=4)
        
        return data["operator"]

    @classmethod
    def get_contacts(cls) -> dict[str, str]:
        """
        Returns a dictionary of all imported contacts {operator_name: public_key}.
        """
        contacts_dir = os.path.join(BASE_DIR, "contacts")
        os.makedirs(contacts_dir, mode=0o700, exist_ok=True)

        contacts = {}
        for f_name in os.listdir(contacts_dir):
            if f_name.endswith(".json"):
                with open(os.path.join(contacts_dir, f_name), "r") as f:
                    data = json.load(f)
                    contacts[data["operator"]] = data["public_key"]
        return contacts