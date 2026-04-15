"""
ANSX Sovereign Identity Mesh — Relay Node
A lightweight federated identity and courier relay for the A.N.SX Vault ecosystem.
"""
import os
import io
import time
import json
import base64
import sqlite3
import hashlib
import logging
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ansx-relay")

DB_PATH = os.environ.get("DB_PATH", "ansx_mesh.db")
MAX_FILE_MB = 20

app = FastAPI(
    title="ANSX Sovereign Identity Mesh",
    description="Federated PKI ledger and ghost courier relay for the A.N.SX Vault network.",
    version="2.0.0",
)

# ─── Database ────────────────────────────────────────────────────────────────

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS identities (
                username    TEXT PRIMARY KEY,
                public_key  TEXT NOT NULL,
                ip_address  TEXT NOT NULL DEFAULT '0.0.0.0',
                registered_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS courier_drops (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient   TEXT NOT NULL,
                sender      TEXT NOT NULL,
                payload_b64 TEXT NOT NULL,
                filename    TEXT NOT NULL,
                dropped_at  INTEGER NOT NULL,
                consumed    INTEGER NOT NULL DEFAULT 0
            );
        """)

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

init_db()

# ─── Models ──────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    public_key: str
    ip_address: str = "0.0.0.0"

class UpdateIPRequest(BaseModel):
    username: str
    ip_address: str

# ─── Identity endpoints ───────────────────────────────────────────────────────

@app.get("/", tags=["Status"])
def root():
    return {"node": "ANSX Sovereign Identity Mesh", "status": "online", "version": "2.0.0"}

@app.post("/v1/identity/register", tags=["Identity"])
def register(req: RegisterRequest):
    with db() as conn:
        existing = conn.execute(
            "SELECT username FROM identities WHERE username = ?", (req.username,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Identity '{req.username}' already anchored to the mesh.")
        conn.execute(
            "INSERT INTO identities (username, public_key, ip_address, registered_at) VALUES (?,?,?,?)",
            (req.username, req.public_key, req.ip_address, int(time.time()))
        )
    logger.info("New identity anchored: %s @ %s", req.username, req.ip_address)
    return {"status": "anchored", "username": req.username}

@app.post("/v1/identity/heartbeat", tags=["Identity"])
def heartbeat(req: UpdateIPRequest):
    """Called each time the app starts to refresh the operator's current IP."""
    with db() as conn:
        row = conn.execute(
            "SELECT username FROM identities WHERE username = ?", (req.username,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Identity not found.")
        conn.execute(
            "UPDATE identities SET ip_address = ? WHERE username = ?",
            (req.ip_address, req.username)
        )
    return {"status": "ok", "ip": req.ip_address}

@app.get("/v1/identity/users", tags=["Identity"])
def list_users():
    with db() as conn:
        rows = conn.execute(
            "SELECT username, ip_address, registered_at FROM identities ORDER BY registered_at"
        ).fetchall()
    return {"users": [dict(r) for r in rows]}

@app.get("/v1/identity/resolve/{username}", tags=["Identity"])
def resolve(username: str):
    with db() as conn:
        row = conn.execute(
            "SELECT username, public_key, ip_address FROM identities WHERE username = ?",
            (username,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Operator '{username}' not found on the mesh.")
    return dict(row)

# ─── Ghost Courier endpoints ──────────────────────────────────────────────────

@app.post("/v1/courier/drop/{recipient}", tags=["Courier"])
async def drop(recipient: str, sender: str = "unknown", file: UploadFile = File(...)):
    """Upload a ghost map image for a recipient. Fails if recipient is not registered."""
    with db() as conn:
        row = conn.execute(
            "SELECT username FROM identities WHERE username = ?", (recipient,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Recipient '{recipient}' not anchored to the mesh.")

    data = await file.read()
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Ghost map exceeds {MAX_FILE_MB}MB limit.")

    payload_b64 = base64.b64encode(data).decode()
    with db() as conn:
        conn.execute(
            "INSERT INTO courier_drops (recipient, sender, payload_b64, filename, dropped_at) VALUES (?,?,?,?,?)",
            (recipient, sender, payload_b64, file.filename or "ghost_map.png", int(time.time()))
        )
    logger.info("Ghost map dropped for '%s' from '%s' (%d bytes)", recipient, sender, len(data))
    return {"status": "delivered", "recipient": recipient}

@app.get("/v1/courier/pickup/{username}", tags=["Courier"])
def pickup(username: str):
    """Check if there are any pending ghost maps for this operator."""
    with db() as conn:
        rows = conn.execute(
            "SELECT id, sender, filename, dropped_at FROM courier_drops "
            "WHERE recipient = ? AND consumed = 0 ORDER BY dropped_at",
            (username,)
        ).fetchall()
    return {"pending": [dict(r) for r in rows]}

@app.get("/v1/courier/download/{drop_id}", tags=["Courier"])
def download(drop_id: int, username: str):
    """Download a specific ghost map drop by ID. Marks it as consumed."""
    with db() as conn:
        row = conn.execute(
            "SELECT recipient, payload_b64, filename FROM courier_drops WHERE id = ? AND consumed = 0",
            (drop_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Drop not found or already consumed.")
        if row["recipient"] != username:
            raise HTTPException(status_code=403, detail="This drop is not addressed to you.")
        conn.execute("UPDATE courier_drops SET consumed = 1 WHERE id = ?", (drop_id,))
        data = base64.b64decode(row["payload_b64"])
    return StreamingResponse(
        io.BytesIO(data),
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{row["filename"]}"'}
    )
