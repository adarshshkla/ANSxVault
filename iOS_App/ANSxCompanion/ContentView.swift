import SwiftUI
import CodeScanner // Optional dependency available via Swift Package Manager

struct ContentView: View {
    @State private var isScanning = false
    @State private var forgedSeed: String = ""
    @State private var serverIP: String = ""
    @State private var statusMessage: String = "Awaiting Mac QR Code"
    
    let nfcWriter = NFCWriter()

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            
            VStack(spacing: 30) {
                Text("A.N.Sx VAULT")
                    .font(.largeTitle)
                    .fontWeight(.heavy)
                    .foregroundColor(.cyan)
                    .tracking(5)
                
                Text(statusMessage)
                    .foregroundColor(.white)
                    .font(.headline)
                    .padding()
                
                if forgedSeed.isEmpty {
                    Button(action: { isScanning = true }) {
                        Text("SCAN GENESIS QR")
                            .font(.headline)
                            .foregroundColor(.black)
                            .padding()
                            .frame(maxWidth: .infinity)
                            .background(Color.cyan)
                            .cornerRadius(12)
                    }
                    .padding(.horizontal, 40)
                } else {
                    Button(action: forgeHardware) {
                        Text("FORGE NFC HARDWARE KEY")
                            .font(.headline)
                            .foregroundColor(.black)
                            .padding()
                            .frame(maxWidth: .infinity)
                            .background(Color.green)
                            .cornerRadius(12)
                    }
                    .padding(.horizontal, 40)
                }
            }
        }
        .sheet(isPresented: $isScanning) {
            // Simulated Scanner (In production, import CodeScanner)
            // CodeScannerView(codeTypes: [.qr], simulatedData: "http://192.168.1.5:5050/provision?seed=ANSX-VAULT-SEED-...") { response in
            //     handleScan(result: response)
            // }
            VStack {
                Text("Camera Scanner View Placeholder")
                Button("Simulate Successful Scan") {
                    handleSimulatedScan(url: "http://192.168.1.5:5050/?seed=ANSX-VAULT-SEED-TEST1234")
                }
            }
        }
    }
    
    func handleSimulatedScan(url: String) {
        guard let urlObj = URL(string: url),
              let components = URLComponents(url: urlObj, resolvingAgainstBaseURL: false),
              let seedItem = components.queryItems?.first(where: { $0.name == "seed" })?.value else {
            return
        }
        
        self.serverIP = "\(urlObj.scheme ?? "http")://\(urlObj.host ?? ""):\(urlObj.port ?? 5050)"
        self.forgedSeed = seedItem
        self.statusMessage = "Target Acquired. Ready to Forge."
        self.isScanning = false
    }
    
    func forgeHardware() {
        self.statusMessage = "Awaiting NFC Contact..."
        nfcWriter.writeSeed(seed: forgedSeed) { success in
            DispatchQueue.main.async {
                if success {
                    self.statusMessage = "Hardware Key Forged!"
                    self.pingMacConfirmation()
                } else {
                    self.statusMessage = "Forging Failed. Try Again."
                }
            }
        }
    }
    
    func pingMacConfirmation() {
        guard let url = URL(string: "\(serverIP)/confirmed") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let json: [String: Any] = ["seed": forgedSeed]
        request.httpBody = try? JSONSerialization.data(withJSONObject: json)
        
        URLSession.shared.dataTask(with: request) { _, _, _ in
            DispatchQueue.main.async {
                self.statusMessage = "Mac Vault Unlocked."
            }
        }.resume()
    }
}
