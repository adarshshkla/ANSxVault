import Foundation
import CoreNFC

class NFCWriter: NSObject, ObservableObject, NFCNDEFReaderSessionDelegate {
    var session: NFCNDEFReaderSession?
    var targetSeed: String = ""
    var onCompletion: ((Bool) -> Void)?

    func writeSeed(seed: String, completion: @escaping (Bool) -> Void) {
        self.targetSeed = seed
        self.onCompletion = completion
        
        session = NFCNDEFReaderSession(delegate: self, queue: nil, invalidateAfterFirstRead: false)
        session?.alertMessage = "Hold your iPhone near the ANSx physical sticker to forge your key."
        session?.begin()
    }

    func readerSession(_ session: NFCNDEFReaderSession, didDetectNDEFs messages: [NFCNDEFMessage]) {
        // Not used for writing
    }

    func readerSession(_ session: NFCNDEFReaderSession, didDetect tags: [NFCNDEFTag]) {
        guard let tag = tags.first else { return }
        
        session.connect(to: tag) { (error: Error?) in
            if error != nil {
                session.alertMessage = "Connection failed. Please try again."
                session.invalidate()
                self.onCompletion?(false)
                return
            }
            
            tag.queryNDEFStatus { (ndefStatus: NFCNDEFStatus, capacity: Int, error: Error?) in
                if ndefStatus == .readWrite {
                    guard let payload = NFCNDEFPayload.wellKnownTypeTextPayload(
                        string: self.targetSeed,
                        locale: Locale(identifier: "en")
                    ) else { return }
                    
                    let ndefMessage = NFCNDEFMessage(records: [payload])
                    
                    tag.writeNDEF(ndefMessage) { (error: Error?) in
                        if error != nil {
                            session.alertMessage = "Write failed!"
                        } else {
                            // Writing successful
                            session.alertMessage = "Cryptographic Forge Successful!"
                        }
                        session.invalidate()
                        self.onCompletion?(error == nil)
                    }
                } else {
                    session.alertMessage = "Tag is locked or not supported."
                    session.invalidate()
                    self.onCompletion?(false)
                }
            }
        }
    }

    func readerSession(_ session: NFCNDEFReaderSession, didInvalidateWithError error: Error) {
        // Handle cancellation or error without crashing
    }
}
