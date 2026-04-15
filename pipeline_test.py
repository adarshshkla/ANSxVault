"""
ANSx Vault — Full Pipeline Verification Test
Tests: Cloud upload simulation → Steganography → UDP loopback → Extraction
"""
import os, sys, json, time, socket, threading, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image

print("\n" + "="*60)
print("  ANSx Vault — Full Pipeline Verification")
print("="*60)

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []

# ─── TEST 1: Cloud Dispatcher (demo mode) ────────────────────────────────────
print("\n[1/4] Testing Cloud Dispatcher (demo mode)...")
try:
    from cloud_dispatcher import CloudDispatcher
    disp = CloudDispatcher()
    urls = {}
    for i in range(11):
        url = disp.upload_shard(i, None, lambda idx, pct: None)
        urls[i] = url
    assert len(urls) == 11, f"Expected 11 URLs, got {len(urls)}"
    assert all(url.startswith("ansx://demo-node") for url in urls.values())
    print(f"  {PASS} — 11 shard URLs generated")
    print(f"  Sample: {urls[0]}")
    results.append(True)
except Exception as e:
    print(f"  {FAIL} — {e}")
    results.append(False)

# ─── TEST 2: Steganography — embed & extract ──────────────────────────────────
print("\n[2/4] Testing Ghost Map Steganography (AES-only mode)...")
try:
    from ghost_map import GhostMap
    import tempfile

    # Create a test carrier image (500x500 white PNG)
    tmp_carrier = tempfile.mktemp(suffix=".png")
    tmp_output  = tempfile.mktemp(suffix=".png")
    img = Image.new("RGB", (500, 500), color=(255, 255, 255))
    img.save(tmp_carrier)

    test_payload = json.dumps({
        "original_file": "test_document.pdf",
        "ephemeral_key": "deadbeefcafe1234" * 4,
        "shard_count": 12,
        "cloud_urls": {str(i): f"ansx://demo-node-{i+1}/shards/frag_{i+1}.ansx" for i in range(11)},
        "shard_12": "SHARD12_BASE64_DATA_HERE",
    })

    # Embed (AES-only, no receiver key yet)
    GhostMap.hide_payload_in_image(test_payload, "", tmp_carrier, tmp_output)
    assert os.path.exists(tmp_output), "Output ghost map not created"
    print(f"  {PASS} — Payload embedded into ghost map ({os.path.getsize(tmp_output):,} bytes)")

    # Extract (AES-only mode, no private key needed for vault-stage)
    extracted = GhostMap.extract_payload_from_image("", tmp_output)
    extracted_data = json.loads(extracted)
    assert extracted_data["original_file"] == "test_document.pdf"
    assert len(extracted_data["cloud_urls"]) == 11
    print(f"  {PASS} — Payload extracted and verified correctly")
    print(f"  File: {extracted_data['original_file']}, Shards: {extracted_data['shard_count']}")

    os.unlink(tmp_carrier)
    os.unlink(tmp_output)
    results.append(True)
except Exception as e:
    print(f"  {FAIL} — {e}")
    import traceback; traceback.print_exc()
    results.append(False)

# ─── TEST 3: UDP Loopback (same machine) ─────────────────────────────────────
print("\n[3/4] Testing UDP loopback delivery (localhost)...")
try:
    from udp_courier import UDPListenerDaemon, ANSX_UDP_Protocol, UDP_PORT, CHUNK_SIZE
    import struct

    received_files = []
    test_img_path  = tempfile.mktemp(suffix=".png")
    img = Image.new("RGB", (200, 200), color=(0, 128, 255))
    img.save(test_img_path)

    # Minimal UDP receive test (direct socket, not full daemon)
    LOOPBACK_PORT = 18099  # different port to avoid conflict

    def receiver_thread():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(("127.0.0.1", LOOPBACK_PORT))
        sock.settimeout(3.0)
        cache = {}
        expected = -1
        try:
            while True:
                data, _ = sock.recvfrom(65535)
                unpacked = ANSX_UDP_Protocol.unpack_chunk(data)
                if unpacked:
                    seq, total, payload = unpacked
                    expected = total
                    cache[seq] = payload
                    if len(cache) == total:
                        sock.sendto(ANSX_UDP_Protocol.pack_ack(), ("127.0.0.1", LOOPBACK_PORT + 1))
                        received_files.append(sum(len(v) for v in cache.values()))
                        break
        except socket.timeout:
            pass
        finally:
            sock.close()

    t = threading.Thread(target=receiver_thread, daemon=True)
    t.start()
    time.sleep(0.1)

    # Send
    with open(test_img_path, "rb") as f:
        file_data = f.read()
    chunks = [file_data[i:i+CHUNK_SIZE] for i in range(0, len(file_data), CHUNK_SIZE)]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for seq, payload in enumerate(chunks):
        pkt = ANSX_UDP_Protocol.pack_chunk(seq, len(chunks), payload)
        sock.sendto(pkt, ("127.0.0.1", LOOPBACK_PORT))
        time.sleep(0.0005)
    sock.close()
    t.join(timeout=4)

    os.unlink(test_img_path)

    if received_files:
        print(f"  {PASS} — UDP delivered {received_files[0]:,} bytes via loopback")
        results.append(True)
    else:
        print(f"  {FAIL} — UDP packets not received on loopback")
        results.append(False)
except Exception as e:
    print(f"  {FAIL} — {e}")
    import traceback; traceback.print_exc()
    results.append(False)

# ─── TEST 4: Web3 Mesh Bridge ─────────────────────────────────────────────────
print("\n[4/4] Testing ANSX Mesh Bridge (relay + cache)...")
try:
    import web3_bridge
    engine = web3_bridge.get_web3_engine()

    # Relay connectivity
    relay_status = "ONLINE" if engine._relay_ok else "OFFLINE (LAN+cache fallback)"
    print(f"  Relay: {relay_status}")

    # Test registration into cache
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    test_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    test_pubkey = test_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()

    # Register into cache (skip if relay rejects duplicate)
    try:
        engine.register_identity("__test_user__", test_pubkey, "192.168.0.99")
    except Exception:
        pass  # might already exist

    fetched = engine.fetch_public_key("__test_user__")
    assert "BEGIN PUBLIC KEY" in fetched
    ip = engine.fetch_ip("__test_user__")
    users = engine.get_all_users()
    assert "__test_user__" in users

    print(f"  {PASS} — Identity registered, public key fetched, IP: {ip}")
    print(f"  {PASS} — get_all_users returned {len(users)} user(s)")
    results.append(True)
except Exception as e:
    print(f"  {FAIL} — {e}")
    import traceback; traceback.print_exc()
    results.append(False)

# ─── Summary ──────────────────────────────────────────────────────────────────
print("\n" + "="*60)
passed = sum(results)
total  = len(results)
print(f"  RESULT: {passed}/{total} tests passed")
if passed == total:
    print("  🎉 ALL SYSTEMS OPERATIONAL — PIPELINE VERIFIED")
else:
    print("  ⚠️  Some components need attention (see above)")
print("="*60 + "\n")
