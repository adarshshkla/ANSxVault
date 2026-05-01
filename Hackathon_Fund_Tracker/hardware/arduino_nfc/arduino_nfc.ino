#include <Wire.h>
#include <Adafruit_PN532.h>

// I2C pins for Arduino Nano: SDA = A4, SCL = A5
#define PN532_IRQ   (2)
#define PN532_RESET (3)  // Not strictly needed for basic I2C

// Initialize the PN532 via I2C
Adafruit_PN532 nfc(PN532_IRQ, PN532_RESET);

void setup(void) {
  Serial.begin(115200);
  while (!Serial) delay(10); // Wait for serial connection

  nfc.begin();

  uint32_t versiondata = nfc.getFirmwareVersion();
  if (!versiondata) {
    Serial.print("ANSX-ERROR: Didn't find PN53x board");
    while (1); // halt
  }

  // Configure board to read RFID tags
  nfc.SAMConfig();
  
  // Ready signal for the Python backend
  Serial.println("ANSX-READY: Waiting for an NFC card...");
}

void loop(void) {
  uint8_t success;
  uint8_t uid[] = { 0, 0, 0, 0, 0, 0, 0 };  // Buffer to store the returned UID
  uint8_t uidLength;                        // Length of the UID (4 or 7 bytes depending on ISO14443A card type)

  // Wait for an ISO14443A type card (Mifare, NTAG, etc.). Timeout 1000ms.
  success = nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLength, 1000);

  if (success) {
    // Send the UID to Python over Serial
    Serial.print("ANSX-UID:");
    for (uint8_t i = 0; i < uidLength; i++) {
      if (uid[i] < 0x10) Serial.print("0");
      Serial.print(uid[i], HEX);
    }
    Serial.println();
    
    // Prevent spamming the same UID multiple times per second
    delay(1500); 
  }
}
