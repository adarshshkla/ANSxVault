import Foundation
import CoreNFC
import UIKit

class NFCReader: NSObject, ObservableObject, NFCTagReaderSessionDelegate {
    var session: NFCTagReaderSession?
    @Published var scannedStatus: String = "Ready to Scan"

    func startScanning() {
        // NFC only works on a physical iPhone, not the simulator
        guard NFCTagReaderSession.readingAvailable else {
            self.scannedStatus = "NFC Not Supported on this device."
            return
        }
        
        // NTAG213 uses ISO14443 polling
        session = NFCTagReaderSession(pollingOption: .iso14443, delegate: self, queue: nil)
        session?.alertMessage = "Hold your NTAG213 to the top of your iPhone to authorize."
        session?.begin()
    }

    func tagReaderSessionDidBecomeActive(_ session: NFCTagReaderSession) { }

    func tagReaderSession(_ session: NFCTagReaderSession, didInvalidateWithError error: Error) {
        DispatchQueue.main.async {
            // Ignore the user-canceled error visually, otherwise show error
            if (error as NSError).code != 200 {
                self.scannedStatus = "Session Ended."
            }
        }
    }

    func tagReaderSession(_ session: NFCTagReaderSession, didDetect tags: [NFCTag]) {
        if tags.count > 1 {
            session.alertMessage = "More than 1 tag detected. Please remove them and try again."
            return
        }
        
        let tag = tags.first!
        
        switch tag {
        case .miFare(let miFareTag):
            // NTAG213 is read as a MiFare tag by CoreNFC
            // Extract the unique hardware ID (UID)
            let uid = miFareTag.identifier.map { String(format: "%02hhx", $0) }.joined()
            let formattedString = "ANSX-UID:\(uid)"
            
            // 1. Copy the UID to the Apple Universal Clipboard
            DispatchQueue.main.async {
                UIPasteboard.general.string = formattedString
                self.scannedStatus = "Copied to Clipboard!\n\(formattedString)"
            }
            
            // 2. Alert the user and close the scanning sheet
            session.alertMessage = "Hardware Authorization Successful!"
            session.invalidate()
            
        default:
            session.invalidate(errorMessage: "Unsupported tag type. Please use an NTAG213.")
        }
    }
}
