"""
nfc_provisioner.py — A.N.Sx Vault NFC Sticker Registration Tool
Generates a downloadable iOS Shortcut (.shortcut) with the seed pre-baked.
iPhone: scan QR -> tap Download Shortcut -> tap Run -> hold sticker -> DONE.
"""

import os
import socket
import threading
import secrets
import plistlib
from flask import Flask, send_file, request, jsonify, render_template_string
import qrcode
import io

app = Flask(__name__)

SESSION_SEED = f"ANSX-VAULT-SEED-{secrets.token_hex(8).upper()}"
PROVISION_COMPLETE = threading.Event()
WRITTEN_SEED = {"value": None}

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()
PORT = 5050


# ─── Build the .shortcut plist ────────────────────────────────────────────────

def build_shortcut_plist(seed: str, confirm_url: str) -> bytes:
    """
    Generates a binary plist Shortcut that:
      1. Writes the seed text to an NFC tag.
      2. POSTs a confirmation back to the Mac automatically.
    """
    shortcut = {
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowClientVersion": "2296.0",
        "WFWorkflowHasShortcutInputVariables": False,
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": -2070375169,   # Neon Purple
            "WFWorkflowIconGlyphNumber": 59511,
        },
        "WFWorkflowImportQuestions": [],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowTypes": [],
        "WFWorkflowActions": [
            # Step 1: Write seed to NFC sticker
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.writenfc",
                "WFWorkflowActionParameters": {
                    "WFInput": {
                        "Value": {"string": seed},
                        "WFSerializationType": "WFTextTokenString",
                    },
                },
            },
            # Step 2: Auto-notify the Mac that writing is done
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
                "WFWorkflowActionParameters": {
                    "WFHTTPMethod": "POST",
                    "WFURL": confirm_url,
                    "WFHTTPBodyType": "JSON",
                    "WFJSONValues": {
                        "Value": {
                            "WFDictionaryFieldValueItems": [
                                {
                                    "WFItemType": 0,
                                    "WFKey": {
                                        "Value": {"string": "seed"},
                                        "WFSerializationType": "WFTextTokenString",
                                    },
                                    "WFValue": {
                                        "Value": {"string": seed},
                                        "WFSerializationType": "WFTextTokenString",
                                    },
                                }
                            ]
                        },
                        "WFSerializationType": "WFDictionaryFieldValue",
                    },
                },
            },
        ],
    }
    return plistlib.dumps(shortcut, fmt=plistlib.FMT_BINARY)


# ─── HTML page served to the iPhone ──────────────────────────────────────────

NFC_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>A.N.Sx Vault — NFC Setup</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    min-height: 100vh;
    background: #090A0F;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    font-family: 'Courier New', monospace;
    color: #E0E2EA;
    padding: 24px;
  }
  .card {
    background: #11121A;
    border: 1px solid #B14CFF;
    border-radius: 16px;
    padding: 36px 28px;
    max-width: 380px; width: 100%;
    box-shadow: 0 0 40px rgba(177,76,255,0.4);
    text-align: center;
  }
  .logo { font-size: 12px; color: #7AA2F7; letter-spacing: 3px; margin-bottom: 8px; }
  h1 { font-size: 22px; font-weight: bold; color: #B14CFF; margin-bottom: 6px;
       text-shadow: 0 0 15px rgba(177,76,255,0.8); }
  .sub { font-size: 13px; color: #7AA2F7; margin-bottom: 24px; line-height: 1.7; }
  .seed {
    background: #1A1B26; border: 1px solid #24283B; border-radius: 8px;
    padding: 12px; font-size: 11px; color: #00F3FF;
    word-break: break-all; margin-bottom: 24px;
    text-shadow: 0 0 8px rgba(0,243,255,0.5);
  }
  .badge {
    display: inline-block; border-radius: 6px; padding: 5px 14px;
    font-size: 11px; font-weight: bold; letter-spacing: 1px; margin-bottom: 20px;
    background: #1A1B26; color: #ff9800; border: 1px solid #ff9800;
  }
  .step-list {
    background: #0d0e16; border: 1px dashed #24283B;
    border-radius: 8px; padding: 16px;
    text-align: left; margin-bottom: 24px;
    font-size: 13px; line-height: 2.2; color: #7AA2F7;
  }
  .step-list b { color: #E0E2EA; }
  .step-list .emphasis { color: #00F3FF; }
  .btn {
    display: block; width: 100%; border: none; border-radius: 10px;
    font-size: 17px; font-weight: bold; padding: 18px;
    cursor: pointer; letter-spacing: 1px; margin-bottom: 12px;
  }
  .btn-dl { background: #B14CFF; color: #fff; box-shadow: 0 0 25px rgba(177,76,255,0.6); }
  .btn-sim { background: #1A1B26; color: #7AA2F7; border: 1px solid #24283B; font-size:13px; padding:12px; }
  .divider { border: none; border-top: 1px solid #24283B; margin: 12px 0; }
  .ok { color: #39FF14; font-size:14px; margin-top:12px; display:none;
        text-shadow: 0 0 10px rgba(57,255,20,0.6); }
</style>
</head>
<body>
<div class="card">
  <div class="logo">A.N.Sx VAULT SYSTEM</div>
  <h1>NFC PROVISIONER</h1>
  <p class="sub">One tap to write your hardware token.<br/>No manual steps required.</p>

  <div class="seed">{{ seed }}</div>

  <div class="badge">ONE-TIME SETUP REQUIRED</div>
  <div class="step-list">
    Before downloading, do this <b>once</b>:<br/>
    <b>Settings</b> → <b>Shortcuts</b><br/>
    → <b>Advanced</b> → Enable<br/>
    <span class="emphasis">"Allow Untrusted Shortcuts"</span>
  </div>

  <a href="/shortcut" class="btn btn-dl" download="ANSxVault_NFC.shortcut">
    ⬇ DOWNLOAD SHORTCUT
  </a>

  <div class="divider"></div>
  <p style="font-size:11px; color:#555; margin-bottom:10px;">After installing the shortcut, tap Run &amp; hold your NFC sticker to the top of your iPhone. The Mac will be notified automatically.</p>

  <button class="btn btn-sim" onclick="simulate()">Testing on same machine? Simulate</button>
  <div class="ok" id="ok">Mac confirmed! Vault token ready.</div>
</div>
<script>
function simulate() {
  fetch('/simulate').then(function() {
    document.getElementById('ok').style.display = 'block';
  });
}
</script>
</body>
</html>
"""


# ─── Flask Routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(NFC_PAGE, seed=SESSION_SEED)

@app.route("/shortcut")
def serve_shortcut():
    """Dynamically generates and serves the .shortcut binary plist."""
    confirm_url = f"http://{LOCAL_IP}:{PORT}/confirmed"
    shortcut_bytes = build_shortcut_plist(SESSION_SEED, confirm_url)
    buf = io.BytesIO(shortcut_bytes)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name="ANSxVault_NFC.shortcut"
    )

@app.route("/confirm", methods=["POST"])    # called by the Shortcut
def confirmed():
    data = request.get_json(silent=True) or {}
    WRITTEN_SEED["value"] = data.get("seed", SESSION_SEED)
    PROVISION_COMPLETE.set()
    return jsonify({"status": "ok"})

@app.route("/confirmed", methods=["POST"])  # alias for Shortcut POST
def confirmed_alias():
    return confirmed()

@app.route("/simulate")                     # Mac browser quick-test
def simulate():
    WRITTEN_SEED["value"] = SESSION_SEED
    PROVISION_COMPLETE.set()
    return "<h2 style='font-family:monospace;color:#39FF14;background:#090A0F;padding:40px;'>Simulated! Check your Mac terminal.</h2>"


# ─── QR + main ────────────────────────────────────────────────────────────────

def print_qr(url: str):
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)

def main():
    url = f"http://{LOCAL_IP}:{PORT}"
    print("\n" + "=" * 62)
    print("  A.N.Sx VAULT -- NFC STICKER PROVISIONER")
    print("=" * 62)
    print(f"\n  Seed: {SESSION_SEED}\n")
    print("  Scan QR with iPhone:\n")
    print_qr(url)
    print(f"\n  URL: {url}")
    print(f"  Local test: {url}/simulate")
    print("\n  Waiting for iPhone to write the sticker...\n")

    server = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False),
        daemon=True
    )
    server.start()
    PROVISION_COMPLETE.wait()

    print("=" * 62)
    print(f"  NFC STICKER PROVISIONED: {WRITTEN_SEED['value']}")
    print("=" * 62)

    seed_path = os.path.expanduser("~/.ansx_vault/nfc_seed.txt")
    os.makedirs(os.path.dirname(seed_path), exist_ok=True)
    with open(seed_path, "w") as f:
        f.write(WRITTEN_SEED["value"])

    print(f"\n  Seed saved to: {seed_path}")
    print("  Launch the Vault — your hardware token is ready.\n")

if __name__ == "__main__":
    main()
