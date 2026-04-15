"""
ANSX Identity Mesh Bridge
Connects the Vault application to the ANSX Sovereign Identity Mesh relay node.
Falls back to LAN discovery + disk cache if the relay is unreachable.
"""
import os
import json
import socket
import logging
import threading
import time
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# ─── Relay URL config ─────────────────────────────────────────────────────────
# Set ANSX_RELAY_URL env var, or configure via the app settings panel.
# Default points to local dev server; replace with your Render/Railway URL.
RELAY_URL = os.environ.get(
    "ANSX_RELAY_URL",
    "https://ansx-sovereign-mesh.onrender.com"   # replace after deployment
).rstrip("/")

_REGISTRY_PATH = os.path.expanduser("~/.ansx_vault/network_registry.json")
_REGISTRY_LOCK = threading.Lock()
_BROADCAST_PORT = 8097
_BROADCAST_INTERVAL = 15

WEB3_ENGINE = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _relay_get(path: str) -> dict:
    url = f"{RELAY_URL}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "ANSxVault/2.0"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


def _relay_post(path: str, payload: dict) -> dict:
    url = f"{RELAY_URL}{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "ANSxVault/2.0"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


# ─── Disk-persisted local cache ───────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        if os.path.exists(_REGISTRY_PATH):
            with open(_REGISTRY_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cache(reg: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_REGISTRY_PATH), exist_ok=True)
        tmp = _REGISTRY_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(reg, f, indent=2)
        os.replace(tmp, _REGISTRY_PATH)
    except Exception as e:
        logger.warning("Cache save failed: %s", e)


def _merge_into_cache(username: str, public_key: str, ip: str):
    with _REGISTRY_LOCK:
        reg = _load_cache()
        reg[username] = {"public_key": public_key, "ip": ip}
        _save_cache(reg)


# ─── LAN broadcast fallback (same WiFi) ──────────────────────────────────────

class _LANDiscovery:
    def __init__(self):
        self._running = False
        self._my_entry = None

    def start_listener(self):
        self._running = True
        t = threading.Thread(target=self._listen_loop, daemon=True, name="ANSX-LAN-Listen")
        t.start()

    def announce(self, username, public_key, ip):
        self._my_entry = {"username": username, "public_key": public_key, "ip": ip}
        t = threading.Thread(target=self._broadcast_loop, daemon=True, name="ANSX-LAN-Bcast")
        t.start()

    def _broadcast_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        msg = json.dumps(self._my_entry).encode()
        while self._running and self._my_entry:
            try:
                sock.sendto(msg, ("255.255.255.255", _BROADCAST_PORT))
            except Exception:
                pass
            time.sleep(_BROADCAST_INTERVAL)
        sock.close()

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            sock.bind(("", _BROADCAST_PORT))
        except Exception as e:
            logger.error("[LAN] Bind failed: %s", e)
            return
        sock.settimeout(1.0)
        while self._running:
            try:
                data, addr = sock.recvfrom(65535)
                entry = json.loads(data.decode())
                u, pk, ip = entry.get("username"), entry.get("public_key"), entry.get("ip", addr[0])
                if u and pk:
                    _merge_into_cache(u, pk, ip)
            except socket.timeout:
                pass
            except Exception:
                pass
        sock.close()

    def stop(self):
        self._running = False


_LAN = _LANDiscovery()


# ─── Main Engine ──────────────────────────────────────────────────────────────

class ANSXMeshEngine:
    """
    Connects to the ANSX Sovereign Identity Mesh for global PKI operations.
    Falls back to LAN broadcast + disk cache when relay is unreachable.
    """

    def __init__(self):
        self._relay_ok = self._ping_relay()
        _LAN.start_listener()
        if self._relay_ok:
            logger.info("[Mesh] Connected to ANSX Sovereign Identity Mesh at %s", RELAY_URL)
        else:
            logger.warning("[Mesh] Relay unreachable, operating in LAN+cache mode.")

    def _ping_relay(self) -> bool:
        try:
            _relay_get("/")
            return True
        except Exception:
            return False

    def register_identity(self, username: str, public_key: str, ip_address: str = None):
        if ip_address is None:
            ip_address = _get_local_ip()

        registered_ok = False
        if self._relay_ok:
            try:
                _relay_post("/v1/identity/register", {
                    "username": username,
                    "public_key": public_key,
                    "ip_address": ip_address,
                })
                registered_ok = True
                logger.info("[Mesh] Identity '%s' anchored to sovereign mesh.", username)
            except urllib.error.HTTPError as e:
                if e.code == 409:
                    # Already registered — send a heartbeat to refresh IP
                    try:
                        _relay_post("/v1/identity/heartbeat", {
                            "username": username, "ip_address": ip_address
                        })
                        registered_ok = True
                    except Exception:
                        pass
                else:
                    logger.warning("[Mesh] Register failed (HTTP %d): %s", e.code, e)
            except Exception as e:
                logger.warning("[Mesh] Register failed: %s", e)

        # Always persist locally too
        _merge_into_cache(username, public_key, ip_address)

        # Broadcast on LAN as well
        _LAN.announce(username, public_key, ip_address)

        if not registered_ok and not self._relay_ok:
            logger.info("[Mesh] Registered locally only (relay offline).")

    def heartbeat(self, username: str):
        """Refresh this operator's IP on the mesh each time the app starts."""
        ip = _get_local_ip()
        if self._relay_ok:
            try:
                _relay_post("/v1/identity/heartbeat", {"username": username, "ip_address": ip})
                logger.info("[Mesh] Heartbeat sent for '%s' @ %s", username, ip)
            except Exception as e:
                logger.warning("[Mesh] Heartbeat failed: %s", e)
        # Also re-broadcast on LAN
        cache = _load_cache()
        entry = cache.get(username, {})
        if entry:
            _LAN.announce(username, entry.get("public_key", ""), ip)

    def fetch_public_key(self, username: str) -> str:
        # Try relay first
        if self._relay_ok:
            try:
                data = _relay_get(f"/v1/identity/resolve/{username}")
                # Also update our local cache with fresh data
                _merge_into_cache(username, data["public_key"], data.get("ip_address", ""))
                return data["public_key"]
            except Exception as e:
                logger.warning("[Mesh] Relay resolve failed, using cache: %s", e)

        # Fall back to local cache
        cache = _load_cache()
        entry = cache.get(username)
        if not entry:
            raise ValueError(f"Operator '{username}' not found on the ANSX Identity Mesh.")
        return entry["public_key"]

    def fetch_ip(self, username: str) -> str:
        if self._relay_ok:
            try:
                data = _relay_get(f"/v1/identity/resolve/{username}")
                return data.get("ip_address", "127.0.0.1")
            except Exception:
                pass
        cache = _load_cache()
        entry = cache.get(username, {})
        return entry.get("ip", "127.0.0.1")

    def get_all_users(self) -> list:
        users = []
        if self._relay_ok:
            try:
                data = _relay_get("/v1/identity/users")
                users = [u["username"] for u in data.get("users", [])]
                # Sync relay users into local cache
                for u in data.get("users", []):
                    pass  # public_key not in list endpoint, resolve lazily
                return users
            except Exception as e:
                logger.warning("[Mesh] get_all_users relay failed, using cache: %s", e)

        # Fall back to cache
        return list(_load_cache().keys())

    def is_registered(self, username: str) -> bool:
        if self._relay_ok:
            try:
                _relay_get(f"/v1/identity/resolve/{username}")
                return True
            except Exception:
                pass
        return username in _load_cache()

    # ── Ghost Courier relay delivery (internet fallback) ──────────────────────

    def drop_ghost_map(self, recipient: str, sender: str, image_path: str) -> bool:
        """Upload a ghost map to the relay inbox for a recipient."""
        if not self._relay_ok:
            return False
        try:
            import urllib.parse
            url = f"{RELAY_URL}/v1/courier/drop/{urllib.parse.quote(recipient)}?sender={urllib.parse.quote(sender)}"
            with open(image_path, "rb") as f:
                file_data = f.read()

            boundary = "----ANSxBoundary7f3k"
            filename = os.path.basename(image_path)
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: image/png\r\n\r\n"
            ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

            req = urllib.request.Request(
                url, data=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "User-Agent": "ANSxVault/2.0",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                result = json.loads(r.read().decode())
                logger.info("[Courier] Ghost map relayed to '%s': %s", recipient, result)
                return True
        except Exception as e:
            logger.error("[Courier] Relay drop failed: %s", e)
            return False

    def check_inbox(self, username: str) -> list:
        """Check for pending ghost maps on the relay for this operator."""
        if not self._relay_ok:
            return []
        try:
            data = _relay_get(f"/v1/courier/pickup/{urllib.parse.quote(username)}")
            return data.get("pending", [])
        except Exception:
            return []

    def download_drop(self, drop_id: int, username: str, save_path: str) -> bool:
        """Download a specific pending ghost map from the relay."""
        if not self._relay_ok:
            return False
        try:
            import urllib.parse
            url = f"{RELAY_URL}/v1/courier/download/{drop_id}?username={urllib.parse.quote(username)}"
            req = urllib.request.Request(url, headers={"User-Agent": "ANSxVault/2.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                with open(save_path, "wb") as f:
                    f.write(r.read())
            logger.info("[Courier] Downloaded drop #%d to %s", drop_id, save_path)
            return True
        except Exception as e:
            logger.error("[Courier] Download failed: %s", e)
            return False


def get_web3_engine() -> ANSXMeshEngine:
    global WEB3_ENGINE
    if WEB3_ENGINE is None:
        WEB3_ENGINE = ANSXMeshEngine()
    return WEB3_ENGINE


# Keep old name for compatibility used in security_core.py
ANSXWeb3Engine = ANSXMeshEngine


import urllib.parse  # ensure available at module level
