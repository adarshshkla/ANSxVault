#!/usr/bin/env bash
# ==============================================================================
#  A.N.SXVault — Hackathon Launch Script
# ==============================================================================

set -e

echo "====================================================================="
echo "   ◈ A.N.SXVault — Public Funds Tracker"
echo "====================================================================="

# 1. Check Python version
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 is required but not installed. Aborting."
    exit 1
fi

# 2. Virtual Environment Setup
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "[SETUP] Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "[SETUP] Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# 3. Install Requirements
echo "[SETUP] Verifying dependencies..."
python3 -m pip install --upgrade pip > /dev/null
python3 -m pip install -r requirements.txt > /dev/null

# 4. Check for .env file
if [ ! -f ".env" ]; then
    echo "[WARN] .env file not found. Copying from .env.example..."
    cp .env.example .env
fi

# 5. Launch the application
echo "[START] Launching Ledger Nexus Production Gateway..."
python3 nexus_launcher.py
