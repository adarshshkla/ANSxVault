import os
import json
import logging
from PIL import Image
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

class GhostMap:
    """
    Implements LSB Image Steganography paired with RSA-4096 Asymmetric Encryption.
    This creates the '12th Shard' physical transport mechanism.

    Two modes:
      MODE 0 (AES-only): Used during vault stage when no receiver is known yet.
                         The AES key is stored raw inside the image.
      MODE 1 (RSA+AES):  Used during send stage. The AES key is RSA-encrypted
                         with the receiver's public key so only they can open it.
    """
    HEADER = b'ANSX'

    @staticmethod
    def _bytes_to_bits(data: bytes) -> list:
        bits = []
        for byte in data:
            for i in range(8):
                bits.append((byte >> (7 - i)) & 1)
        return bits

    @staticmethod
    def _bits_to_bytes(bits: list) -> bytes:
        bytes_out = bytearray()
        for i in range(0, len(bits), 8):
            byte = 0
            for bit in bits[i:i + 8]:
                byte = (byte << 1) | bit
            bytes_out.append(byte)
        return bytes(bytes_out)

    @classmethod
    def hide_payload_in_image(
        cls,
        json_payload: str,
        receiver_pub_key_pem: str,
        carrier_img_path: str,
        output_img_path: str
    ) -> None:
        """
        Embeds an encrypted JSON payload into a carrier image using LSB steganography.

        If receiver_pub_key_pem is a valid PEM public key → MODE 1 (RSA+AES hybrid).
        Otherwise                                          → MODE 0 (AES-only, vault stage).
        """
        # Step 1: AES-GCM encrypt the payload
        payload_aes_key = AESGCM.generate_key(bit_length=256)
        aesgcm = AESGCM(payload_aes_key)
        nonce = os.urandom(12)
        encrypted_payload = aesgcm.encrypt(nonce, json_payload.encode('utf-8'), None)

        # Step 2: Decide mode based on whether a real PEM public key was provided
        use_rsa = bool(
            receiver_pub_key_pem
            and receiver_pub_key_pem.strip().startswith("-----BEGIN")
        )

        payload_len_bytes = len(encrypted_payload).to_bytes(4, byteorder='big')

        if use_rsa:
            # MODE 1: RSA wraps the AES key
            pub_key = serialization.load_pem_public_key(receiver_pub_key_pem.encode('utf-8'))
            encrypted_aes_key = pub_key.encrypt(
                payload_aes_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            # Layout: HEADER(4) + MODE(1) + LEN(4) + RSA_KEY(512) + NONCE(12) + PAYLOAD
            full_payload = (
                cls.HEADER + b'\x01' + payload_len_bytes
                + encrypted_aes_key + nonce + encrypted_payload
            )
            mode_tag = "RSA+AES"
        else:
            # MODE 0: raw AES key stored inside image (vault stage — no receiver yet)
            # Layout: HEADER(4) + MODE(0) + LEN(4) + AES_KEY(32) + NONCE(12) + PAYLOAD
            full_payload = (
                cls.HEADER + b'\x00' + payload_len_bytes
                + payload_aes_key + nonce + encrypted_payload
            )
            mode_tag = "AES-only (vault stage)"

        # Step 3: Embed into image pixels using LSB steganography
        bits = cls._bytes_to_bits(full_payload)

        img = Image.open(carrier_img_path)
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')

        pixels = img.load()
        width, height = img.size

        if len(bits) > width * height * 3:
            raise ValueError(
                f"Carrier image too small: need {len(bits)} bits, "
                f"image has {width * height * 3} bits of capacity."
            )

        bit_idx = 0
        for y in range(height):
            for x in range(width):
                if bit_idx >= len(bits):
                    break
                pixel = list(pixels[x, y])
                for c in range(3):
                    if bit_idx < len(bits):
                        pixel[c] = (pixel[c] & ~1) | bits[bit_idx]
                        bit_idx += 1
                if len(pixel) == 4:
                    pixels[x, y] = (pixel[0], pixel[1], pixel[2], pixel[3])
                else:
                    pixels[x, y] = (pixel[0], pixel[1], pixel[2])
            if bit_idx >= len(bits):
                break

        img.save(output_img_path, format="PNG")
        logger.info("Ghost Map forged [%s] → %s", mode_tag, output_img_path)

    @classmethod
    def extract_payload_from_image(cls, private_key_pem: str, courier_img_path: str) -> str:
        """
        Extracts the encrypted payload from a Ghost Map image and decrypts it.
        Supports both MODE 0 (AES-only) and MODE 1 (RSA+AES).
        """
        img = Image.open(courier_img_path)
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')

        pixels = img.load()
        width, height = img.size

        # Read enough bits for header + mode + length field = 4+1+4 = 9 bytes = 72 bits
        HEADER_BITS = 9 * 8
        extracted_bits = []

        for y in range(height):
            for x in range(width):
                pixel = pixels[x, y]
                for c in range(3):
                    extracted_bits.append(pixel[c] & 1)
                    if len(extracted_bits) >= HEADER_BITS:
                        break
                if len(extracted_bits) >= HEADER_BITS:
                    break
            if len(extracted_bits) >= HEADER_BITS:
                break

        header_bytes = cls._bits_to_bytes(extracted_bits[:HEADER_BITS])
        if not header_bytes.startswith(cls.HEADER):
            raise ValueError("Magic header missing — not a Ghost Map image.")

        mode = header_bytes[4]
        payload_length = int.from_bytes(header_bytes[5:9], byteorder='big')

        # Determine key block size
        key_block_size = 512 if mode == 1 else 32  # RSA-4096 output vs raw AES-256 key
        total_bytes = 9 + key_block_size + 12 + payload_length  # header+mode+len, key, nonce, payload
        total_bits = total_bytes * 8

        # Read all required bits
        extracted_bits = []
        for y in range(height):
            for x in range(width):
                pixel = pixels[x, y]
                for c in range(3):
                    extracted_bits.append(pixel[c] & 1)
                    if len(extracted_bits) >= total_bits:
                        break
                if len(extracted_bits) >= total_bits:
                    break
            if len(extracted_bits) >= total_bits:
                break

        all_bytes = cls._bits_to_bytes(extracted_bits)
        key_block = all_bytes[9: 9 + key_block_size]
        nonce = all_bytes[9 + key_block_size: 9 + key_block_size + 12]
        encrypted_payload = all_bytes[9 + key_block_size + 12:]

        if mode == 1:
            # MODE 1: decrypt AES key using private key
            priv_key = serialization.load_pem_private_key(
                private_key_pem.encode('utf-8'), password=None
            )
            payload_aes_key = priv_key.decrypt(
                key_block,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
        else:
            # MODE 0: AES key stored directly
            payload_aes_key = key_block

        aesgcm = AESGCM(payload_aes_key)
        decrypted_json = aesgcm.decrypt(nonce, encrypted_payload, None)
        return decrypted_json.decode('utf-8')
