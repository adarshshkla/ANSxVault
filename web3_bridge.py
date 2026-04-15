import os
import json
import logging
from web3 import Web3
from eth_tester import EthereumTester
import solcx

logger = logging.getLogger(__name__)

# Ensure solc is installed
try:
    solcx.install_solc('0.8.0')
except Exception as e:
    logger.warning("solc install failed: %s", e)

class ANSXWeb3Engine:
    def __init__(self):
        self.w3 = Web3(Web3.EthereumTesterProvider(EthereumTester()))
        self.contract_address = None
        self.contract = None
        
        # We use the first generated test account
        self.account = self.w3.eth.accounts[0]
        self._deploy_contract()

    def _deploy_contract(self):
        try:
            contract_path = os.path.join(os.path.dirname(__file__), "ANSXRegistry.sol")
            with open(contract_path, "r") as f:
                contract_src = f.read()

            compiled_sol = solcx.compile_source(
                contract_src,
                output_values=['abi', 'bin'],
                solc_version='0.8.0'
            )
            
            contract_id, contract_interface = compiled_sol.popitem()
            bytecode = contract_interface['bin']
            abi = contract_interface['abi']
            
            Registry = self.w3.eth.contract(abi=abi, bytecode=bytecode)
            tx_hash = Registry.constructor().transact({'from': self.account})
            tx_receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            
            self.contract_address = tx_receipt.contractAddress
            self.contract = self.w3.eth.contract(address=self.contract_address, abi=abi)
            logger.info(f"Web3 Engine Booted. Registry Contract deployed at: {self.contract_address}")
        except Exception as e:
            logger.error("Smart Contract compilation/deployment failed: %s", e)
            raise e

    def register_identity(self, username: str, public_key: str, ip_address: str = "0.0.0.0"):
        tx_hash = self.contract.functions.registerProfile(
            username, 
            public_key, 
            ip_address
        ).transact({'from': self.account})
        self.w3.eth.wait_for_transaction_receipt(tx_hash)

    def fetch_public_key(self, username: str) -> str:
        return self.contract.functions.getPublicKey(username).call()
        
    def fetch_ip(self, username: str) -> str:
        return self.contract.functions.getIPAddress(username).call()

# Global Singleton
WEB3_ENGINE = None

def get_web3_engine():
    global WEB3_ENGINE
    if not WEB3_ENGINE:
        WEB3_ENGINE = ANSXWeb3Engine()
    return WEB3_ENGINE
