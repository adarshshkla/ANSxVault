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
    """
    HEADER = b'ANSX'

    @staticmethod
    def _bytes_to_bits(data: bytes) -> list[int]:
        bits = []
        for byte in data:
            for i in range(8):
                bits.append((byte >> (7 - i)) & 1)
        return bits

    @staticmethod
    def _bits_to_bytes(bits: list[int]) -> bytes:
        bytes_out = bytearray()
        for i in range(0, len(bits), 8):
            byte = 0
            for bit in bits[i:i+8]:
                byte = (byte << 1) | bit
            bytes_out.append(byte)
        return bytes(bytes_out)

    @classmethod
    def hide_payload_in_image(cls, json_payload: str, receiver_pub_key_pem: str, carrier_img_path: str, output_img_path: str) -> None:
        """
        Encrypts an arbitrary length JSON payload using Hybrid Envelope Encryption (AES-GCM + RSA),
        and embeds it into the carrier image pixels.
        """
        try:
            # 1. Envelope Encryption: Generate ephemeral AES key for the payload
            payload_aes_key = AESGCM.generate_key(bit_length=256)
            aesgcm = AESGCM(payload_aes_key)
            nonce = os.urandom(12)
            encrypted_payload = aesgcm.encrypt(nonce, json_payload.encode('utf-8'), None)

            # 2. RSA Encrypt the payload AES key (not the master vault key, just the transport key!)
            pub_key = serialization.load_pem_public_key(receiver_pub_key_pem.encode('utf-8'))
            encrypted_aes_key = pub_key.encrypt(
                payload_aes_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            # 3. Serialize: HEADER (4) + Payload Length (4) + RSA(AES)(512) + Nonce(12) + AES(Payload)(X)
            payload_len_bytes = len(encrypted_payload).to_bytes(4, byteorder='big')
            full_payload = cls.HEADER + payload_len_bytes + encrypted_aes_key + nonce + encrypted_payload
            bits = cls._bytes_to_bits(full_payload)

            img = Image.open(carrier_img_path)
            if img.mode != 'RGB' and img.mode != 'RGBA':
                img = img.convert('RGB')
            
            pixels = img.load()
            width, height = img.size
            if len(bits) > width * height * 3:
                raise ValueError("Carrier image is too small to hold the 512-byte payload.")

            bit_idx = 0
            for y in range(height):
                for x in range(width):
                    if bit_idx >= len(bits):
                        break
                    
                    pixel = list(pixels[x, y])
                    # Iterate through R, G, B channels
                    for c in range(3):
                        if bit_idx < len(bits):
                            # Set LSB to payload bit
                            pixel[c] = (pixel[c] & ~1) | bits[bit_idx]
                            bit_idx += 1
                        
                    if len(pixel) == 4: # RGBA
                        pixels[x, y] = (pixel[0], pixel[1], pixel[2], pixel[3])
                    else:
                        pixels[x, y] = (pixel[0], pixel[1], pixel[2])
                
                if bit_idx >= len(bits):
                    break

            img.save(output_img_path, format="PNG")
            logger.info("Successfully forged Ghost Map at %s", output_img_path)

        except Exception as e:
            logger.error("Failed to inject Steganography payload: %s", e)
            raise

    @classmethod
    def extract_payload_from_image(cls, private_key_pem: str, courier_img_path: str) -> str:
        """
        Extracts the RSA cipher from an image, decrypts the Envelope AES key, and decrypts the JSON payload.
        """
        img = Image.open(courier_img_path)
        if img.mode != 'RGB' and img.mode != 'RGBA':
            img = img.convert('RGB')
        
        pixels = img.load()
        width, height = img.size
        
        # We don't know total target bits yet, read header + length + rsa + nonce first
        # Header (4) + Len (4) + RSA (512) + Nonce (12) = 532 bytes (4256 bits)
        initial_target_bits = 532 * 8
        extracted_bits = []
        full_payload_bits = -1

        for y in range(height):
            for x in range(width):
                pixel = pixels[x, y]
                for c in range(3):
                    extracted_bits.append(pixel[c] & 1)
                    
                    if len(extracted_bits) == initial_target_bits:
                        header_block = cls._bits_to_bytes(extracted_bits[:64]) # 8 bytes: Header(4) + Len(4)
                        if not header_block.startswith(cls.HEADER):
                            raise ValueError("Steganography failed: Magic Header Missing.")
                        
                        payload_length = int.from_bytes(header_block[4:8], byteorder='big')
                        full_payload_bits = initial_target_bits + (payload_length * 8)
                        
                    if full_payload_bits != -1 and len(extracted_bits) >= full_payload_bits:
                        break
                if full_payload_bits != -1 and len(extracted_bits) >= full_payload_bits:
                    break
            if full_payload_bits != -1 and len(extracted_bits) >= full_payload_bits:
                break
                
        full_payload_bytes = cls._bits_to_bytes(extracted_bits)
        encrypted_aes_key = full_payload_bytes[8:520]
        nonce = full_payload_bytes[520:532]
        encrypted_payload = full_payload_bytes[532:]
        
        try:
            priv_key = serialization.load_pem_private_key(
                private_key_pem.encode('utf-8'),
                password=None
            )
            payload_aes_key = priv_key.decrypt(
                encrypted_aes_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            aesgcm = AESGCM(payload_aes_key)
            decrypted_json = aesgcm.decrypt(nonce, encrypted_payload, None)
            return decrypted_json.decode('utf-8')
            img = img.convert('RGB')
        
        except Exception as e:
            logger.error("Decryption failed. Invalid Receiver DNA. %s", e)
            raise
