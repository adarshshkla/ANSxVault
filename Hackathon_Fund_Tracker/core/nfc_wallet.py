import time
import hashlib
import subprocess

# Hardware salt - this ensures that even if someone knows the NFC UID,
# they cannot derive the key without knowing the server's local entropy.
HARDWARE_SALT = "ANSX-Hackathon-Salt-2026"

# Production Identity Mode
# Uses the physical iPhone Universal Clipboard to receive the NFC UID signature.

def get_clipboard_text():
    """Reads text from the macOS clipboard."""
    try:
        # pbpaste is a built-in command on macOS
        result = subprocess.run(['pbpaste'], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        return ""

def clear_clipboard():
    """Clears the macOS clipboard for security."""
    try:
        subprocess.run(['pbcopy'], input="", text=True)
    except Exception:
        pass

def derive_web3_private_key(nfc_uid: str) -> str:
    """
    Takes the physical NFC UID, mixes it with the salt, 
    and mathematically derives a Web3-compatible Private Key (32 bytes / 64 hex chars).
    """
    combined_entropy = f"{nfc_uid}-{HARDWARE_SALT}".encode('utf-8')
    
    # Generate SHA-256 hash (this creates exactly 32 bytes of entropy)
    hash_obj = hashlib.sha256(combined_entropy)
    private_key_hex = hash_obj.hexdigest()
    
    # Ensure it looks like a standard Ethereum private key with '0x' prefix
    return f"0x{private_key_hex}"

def wait_for_hardware_tap(timeout=60):
    """
    Monitors the macOS clipboard for the NFC signature sent from the iPhone
    via Universal Clipboard.

    Returns:
        (private_key: str, full_uid: str) tuple — full_uid is the complete
        'ANSX-UID:...' string so the caller can look it up in the registry.
        Returns None on timeout or error.
    """
    print("[SYSTEM] Monitoring Apple Universal Clipboard for iPhone NFC scan...")

    clear_clipboard()

    start_time     = time.time()
    last_clipboard = ""

    try:
        while (time.time() - start_time) < timeout:
            current_clipboard = get_clipboard_text()

            if current_clipboard != last_clipboard and "ANSX-UID:" in current_clipboard:
                # Extract the suffix after "ANSX-UID:"
                full_uid  = current_clipboard.strip()          # e.g. "ANSX-UID:Admin_Tag_001"
                uid_suffix = full_uid.split("ANSX-UID:", 1)[1].strip()

                print(f"\n[+] iPhone Universal Clipboard — UID received: {full_uid}")

                private_key = derive_web3_private_key(uid_suffix)
                clear_clipboard()

                # Return both key AND the full UID string for registry lookup
                return (private_key, full_uid)

            last_clipboard = current_clipboard
            time.sleep(0.5)

        raise Exception("Hardware Timeout: No NFC tag scanned within the time limit.")

    except Exception as e:
        print(f"\n[ERROR] Clipboard interface failed: {e}")
        return None


if __name__ == "__main__":
    print("="*55)
    print("   A.N.SXVault iPhone Hardware Escrow Initializing...")
    print("="*55)
    
    try:
        # Wait up to 60 seconds for an iPhone tap
        derived_key = wait_for_hardware_tap(timeout=60)
        
        if derived_key:
            print(f"\n[SUCCESS] Web3 Private Key Derived in Volatile RAM!")
            print(f"[*] Derived Key: {derived_key}")
            print("\n[SECURITY] WARNING: Key will be wiped from memory upon process exit.")
            print("="*55)
    except KeyboardInterrupt:
        print("\n[SYSTEM] Operation Cancelled.")
