// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/**
 * @title ANSXRegistry
 * @dev Immutable Decentralized Contact Book for the A.N.SXVault ecosystem.
 */
contract ANSXRegistry {
    
    // Map an ANSX Username to their RSA-4096 Public Key PEM string
    mapping(string => string) private publicKeys;
    
    // Map an ANSX Username to an optional IP address for UDP P2P Routing
    mapping(string => string) private userIPs;

    // Map a username to a boolean to prevent overwriting keys
    mapping(string => bool) private isRegistered;

    // Track all registered usernames for enumeration
    string[] private userList;

    event ProfileRegistered(string indexed username, string pubKey, string ipAddress);

    /**
     * @dev Register a new operator's public identity.
     * @param username The unique handle for the operator.
     * @param pubKey The RSA-4096 public key.
     * @param ipAddr The optional IPv4 address for P2P connection.
     */
    function registerProfile(string memory username, string memory pubKey, string memory ipAddr) public {
        require(!isRegistered[username], "Username already registered on the blockchain.");
        
        publicKeys[username] = pubKey;
        userIPs[username] = ipAddr;
        isRegistered[username] = true;
        userList.push(username);
        
        emit ProfileRegistered(username, pubKey, ipAddr);
    }

    /**
     * @dev Fetch an operator's public key.
     */
    function getPublicKey(string memory username) public view returns (string memory) {
        require(isRegistered[username], "Operator not found in the blockchain registry.");
        return publicKeys[username];
    }
    
    /**
     * @dev Fetch an operator's P2P IP address.
     */
    function getIPAddress(string memory username) public view returns (string memory) {
        return userIPs[username];
    }

    /**
     * @dev Returns all registered usernames for populating dropdowns.
     */
    function getAllUsers() public view returns (string[] memory) {
        return userList;
    }

    /**
     * @dev Check if a username is registered.
     */
    function isUserRegistered(string memory username) public view returns (bool) {
        return isRegistered[username];
    }
}
