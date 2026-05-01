// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/**
 * @title FundVault v2 — Government-Grade Public Fund Tracker
 * @notice Multi-sig approvals, milestone gates, vendor registry, audit events
 */
contract FundVault {

    // ─── Roles ───────────────────────────────────────────────────────────
    address public owner;
    address public kycOracle;
    mapping(address => bool) public auditors;

    // ─── Vendor Registry ─────────────────────────────────────────────────
    struct Vendor {
        string  name;
        string  gstNumber;
        bool    approved;
        uint8   rating;       // 0–50 (maps to 0.0–5.0 stars × 10)
        uint256 ratingCount;
        uint256 totalScore;
    }
    mapping(address => Vendor) public vendors;
    address[] public vendorList;

    // ─── Budget Heads ─────────────────────────────────────────────────────
    struct BudgetHead {
        string  name;
        uint256 ceiling;
        uint256 spent;
    }
    mapping(bytes32 => BudgetHead) public budgets;  // key = keccak256(departmentName)
    bytes32[] public budgetKeys;

    // ─── Escrow ───────────────────────────────────────────────────────────
    enum EscrowStatus { PENDING, APPROVED, RELEASED, FROZEN, CANCELLED }

    struct Escrow {
        address  vendor;
        uint256  amount;
        uint256  releaseTime;
        EscrowStatus status;
        // Multi-sig
        uint256  approvalCount;
        // Milestone
        bytes32  milestoneHash;     // hash of completion document; 0x0 = not submitted
        bool     milestoneRequired;
        // Budget tracking
        bytes32  budgetKey;
        // Metadata
        string   purpose;
        // Voting
        uint256  unfreezeVotes;
        uint256  cancelVotes;
        // SLA Escalation
        uint256  escalationDeadline;
    }

    mapping(uint256 => Escrow) public escrows;
    uint256 public escrowCounter;

    uint256 public requiredApprovals = 2;   // N-of-M multi-sig threshold
    uint256 public requiredVotes     = 2;   // votes needed for unfreeze/cancel

    mapping(uint256 => mapping(address => bool)) public hasApproved;
    mapping(uint256 => mapping(address => bool)) public hasVotedUnfreeze;
    mapping(uint256 => mapping(address => bool)) public hasVotedCancel;

    // ─── Events ───────────────────────────────────────────────────────────
    event Deposit(address indexed sender, uint256 amount);
    event EscrowCreated(uint256 indexed id, address indexed vendor, uint256 amount, string purpose);
    event EscrowApproved(uint256 indexed id, address indexed approver, uint256 approvalCount);
    event EscrowReleased(uint256 indexed id, address indexed vendor, uint256 amount);
    event EscrowFrozen(uint256 indexed id, address indexed auditor);
    event EscrowUnfrozen(uint256 indexed id);
    event EscrowCancelled(uint256 indexed id, uint256 amountReturned);
    event MilestoneSubmitted(uint256 indexed id, bytes32 docHash, address indexed auditor);
    event VendorRegistered(address indexed vendor, string name);
    event VendorRated(address indexed vendor, uint8 score);
    event BudgetCreated(bytes32 indexed key, string name, uint256 ceiling);
    event AuditEvent(address indexed actor, string action, uint256 indexed escrowId);
    event AuditorAdded(address indexed auditor);
    event EscrowEscalated(uint256 indexed id, address indexed initiator);

    // ─── Modifiers ────────────────────────────────────────────────────────
    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner");
        _;
    }
    modifier onlyAuditor() {
        require(auditors[msg.sender], "Only auditor");
        _;
    }
    modifier onlyAuthorized() {
        require(msg.sender == owner || auditors[msg.sender], "Not authorized");
        _;
    }

    constructor() {
        owner = msg.sender;
        auditors[msg.sender] = true;
    }

    // ─── Admin: Role Management ───────────────────────────────────────────
    function addAuditor(address _auditor) external onlyOwner {
        auditors[_auditor] = true;
        emit AuditorAdded(_auditor);
    }

    function setKycOracle(address _oracle) external onlyOwner {
        kycOracle = _oracle;
    }

    function setRequiredApprovals(uint256 n) external onlyOwner {
        require(n >= 1, "At least 1 approval");
        requiredApprovals = n;
    }

    function setRequiredVotes(uint256 n) external onlyOwner {
        requiredVotes = n;
    }

    // ─── Treasury ─────────────────────────────────────────────────────────
    function depositFunds() external payable {
        emit Deposit(msg.sender, msg.value);
    }

    receive() external payable {
        emit Deposit(msg.sender, msg.value);
    }

    // ─── Vendor Registry (ZK-KYC) ────────────────────────────────────────
    function registerVendor(
        address _vendor, 
        string calldata _name, 
        string calldata _gst,
        bytes memory _taxProofSignature
    ) external onlyOwner {
        require(kycOracle != address(0), "KYC Oracle not set");
        
        // Verify the Oracle signature: [vendorAddress, gstNumber, "TAX_CLEARED"]
        bytes32 messageHash = keccak256(abi.encodePacked(_vendor, _gst, "TAX_CLEARED"));
        bytes32 ethSignedMessageHash = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", messageHash));
        require(recoverSigner(ethSignedMessageHash, _taxProofSignature) == kycOracle, "Invalid KYC Oracle Signature");

        if (!vendors[_vendor].approved) {
            vendorList.push(_vendor);
        }
        vendors[_vendor] = Vendor({
            name:        _name,
            gstNumber:   _gst,
            approved:    true,
            rating:      0,
            ratingCount: 0,
            totalScore:  0
        });
        emit VendorRegistered(_vendor, _name);
    }

    function deregisterVendor(address _vendor) external onlyOwner {
        vendors[_vendor].approved = false;
    }

    function rateVendor(address _vendor, uint8 _score) external onlyAuthorized {
        require(_score <= 50, "Score max 50");
        Vendor storage v = vendors[_vendor];
        v.ratingCount++;
        v.totalScore += _score;
        v.rating = uint8(v.totalScore / v.ratingCount);
        emit VendorRated(_vendor, _score);
    }

    function isVendorApproved(address _vendor) public view returns (bool) {
        return vendors[_vendor].approved;
    }

    function getVendorCount() external view returns (uint256) {
        return vendorList.length;
    }

    // ─── Budget Heads ─────────────────────────────────────────────────────
    function createBudget(string calldata _name, uint256 _ceiling) external onlyOwner {
        bytes32 key = keccak256(bytes(_name));
        if (budgets[key].ceiling == 0) {
            budgetKeys.push(key);
        }
        budgets[key] = BudgetHead({ name: _name, ceiling: _ceiling, spent: budgets[key].spent });
        emit BudgetCreated(key, _name, _ceiling);
    }

    function getBudgetCount() external view returns (uint256) {
        return budgetKeys.length;
    }

    // ─── Escrow: Create ───────────────────────────────────────────────────
    function createEscrow(
        address  _vendor,
        uint256  _amount,
        uint256  _lockDuration,
        string   calldata _purpose,
        bool     _milestoneRequired,
        bytes32  _budgetKey
    ) external onlyOwner {
        require(address(this).balance >= _amount, "Insufficient funds in treasury");
        require(_vendor != address(0), "Invalid vendor address");

        // Budget check
        if (_budgetKey != bytes32(0)) {
            BudgetHead storage b = budgets[_budgetKey];
            require(b.ceiling > 0, "Budget head not found");
            require(b.spent + _amount <= b.ceiling, "Exceeds budget ceiling");
            b.spent += _amount;
        }

        uint256 id = escrowCounter++;
        escrows[id] = Escrow({
            vendor:            _vendor,
            amount:            _amount,
            releaseTime:       block.timestamp + _lockDuration,
            status:            EscrowStatus.PENDING,
            approvalCount:     0,
            milestoneHash:     bytes32(0),
            milestoneRequired: _milestoneRequired,
            budgetKey:         _budgetKey,
            purpose:           _purpose,
            unfreezeVotes:     0,
            cancelVotes:       0,
            escalationDeadline: block.timestamp + 120 // 2 minutes for demo purposes (e.g. 14 days in prod)
        });

        emit EscrowCreated(id, _vendor, _amount, _purpose);
        emit AuditEvent(msg.sender, "ESCROW_CREATED", id);
    }

    // ─── Escrow: Multi-Sig Approval ───────────────────────────────────────
    function approveRelease(uint256 _id) external onlyAuthorized {
        Escrow storage e = escrows[_id];
        require(e.status == EscrowStatus.PENDING, "Not pending");
        require(!hasApproved[_id][msg.sender], "Already approved");

        hasApproved[_id][msg.sender] = true;
        e.approvalCount++;

        emit EscrowApproved(_id, msg.sender, e.approvalCount);
        emit AuditEvent(msg.sender, "ESCROW_APPROVED", _id);

        // Auto-release if milestone satisfied AND enough approvals
        if (e.approvalCount >= requiredApprovals) {
            if (!e.milestoneRequired || e.milestoneHash != bytes32(0)) {
                _release(_id);
            } else {
                e.status = EscrowStatus.APPROVED;  // waiting for milestone
            }
        }
    }

    // ─── Escrow: Milestone Submission ─────────────────────────────────────
    function submitMilestone(uint256 _id, bytes32 _docHash) external onlyAuditor {
        Escrow storage e = escrows[_id];
        require(e.status == EscrowStatus.PENDING || e.status == EscrowStatus.APPROVED, "Invalid state");
        require(e.milestoneRequired, "No milestone required");
        require(e.milestoneHash == bytes32(0), "Milestone already submitted");

        e.milestoneHash = _docHash;
        emit MilestoneSubmitted(_id, _docHash, msg.sender);
        emit AuditEvent(msg.sender, "MILESTONE_SUBMITTED", _id);

        // If already has enough approvals, auto-release now
        if (e.status == EscrowStatus.APPROVED && e.approvalCount >= requiredApprovals) {
            _release(_id);
        }
    }

    // ─── Escrow: Internal Release ─────────────────────────────────────────
    function _release(uint256 _id) internal {
        Escrow storage e = escrows[_id];
        e.status = EscrowStatus.RELEASED;
        payable(e.vendor).transfer(e.amount);
        emit EscrowReleased(_id, e.vendor, e.amount);
        emit AuditEvent(e.vendor, "ESCROW_RELEASED", _id);
    }

    // ─── Escrow: Vendor Withdraw (time-locked) ────────────────────────────
    function withdraw(uint256 _id) external {
        Escrow storage e = escrows[_id];
        require(msg.sender == e.vendor, "Only vendor");
        require(block.timestamp >= e.releaseTime, "Time-lock active");
        require(e.status == EscrowStatus.PENDING, "Not pending");
        require(!e.milestoneRequired || e.milestoneHash != bytes32(0), "Milestone required");
        require(e.approvalCount >= requiredApprovals, "Insufficient approvals");
        _release(_id);
    }

    // ─── Escrow: Freeze / Unfreeze / Cancel ───────────────────────────────
    function freezeTransaction(uint256 _id) external onlyAuditor {
        Escrow storage e = escrows[_id];
        require(e.status == EscrowStatus.PENDING || e.status == EscrowStatus.APPROVED, "Cannot freeze");
        e.status = EscrowStatus.FROZEN;
        emit EscrowFrozen(_id, msg.sender);
        emit AuditEvent(msg.sender, "ESCROW_FROZEN", _id);
    }

    function voteToUnfreeze(uint256 _id) external onlyAuditor {
        Escrow storage e = escrows[_id];
        require(e.status == EscrowStatus.FROZEN, "Not frozen");
        require(!hasVotedUnfreeze[_id][msg.sender], "Already voted");
        hasVotedUnfreeze[_id][msg.sender] = true;
        e.unfreezeVotes++;
        if (e.unfreezeVotes >= requiredVotes) {
            e.status = EscrowStatus.PENDING;
            e.unfreezeVotes = 0;
            e.cancelVotes   = 0;
            emit EscrowUnfrozen(_id);
        }
    }

    function voteToCancel(uint256 _id) external onlyAuditor {
        Escrow storage e = escrows[_id];
        require(e.status == EscrowStatus.FROZEN, "Not frozen");
        require(!hasVotedCancel[_id][msg.sender], "Already voted");
        hasVotedCancel[_id][msg.sender] = true;
        e.cancelVotes++;
        if (e.cancelVotes >= requiredVotes) {
            e.status = EscrowStatus.CANCELLED;
            emit EscrowCancelled(_id, e.amount);
            emit AuditEvent(msg.sender, "ESCROW_CANCELLED", _id);
        }
    }

    // ─── View Helpers ─────────────────────────────────────────────────────
    function getEscrowApprovals(uint256 _id) external view returns (uint256 count, bool milestoneOk) {
        Escrow storage e = escrows[_id];
        return (e.approvalCount, !e.milestoneRequired || e.milestoneHash != bytes32(0));
    }

    function getEscrowStatus(uint256 _id) external view returns (
        uint8 status, uint256 approvals, bool milestoneOk, bytes32 milestoneHash
    ) {
        Escrow storage e = escrows[_id];
        return (
            uint8(e.status),
            e.approvalCount,
            !e.milestoneRequired || e.milestoneHash != bytes32(0),
            e.milestoneHash
        );
    }

    // ─── SLA Auto-Escalation ──────────────────────────────────────────────
    function escalateAndRelease(uint256 _id) external onlyAuthorized {
        Escrow storage e = escrows[_id];
        require(e.status == EscrowStatus.PENDING || e.status == EscrowStatus.APPROVED, "Not pending or approved");
        require(block.timestamp > e.escalationDeadline, "Deadline not passed");
        require(!e.milestoneRequired || e.milestoneHash != bytes32(0), "Milestone not met");

        e.status = EscrowStatus.RELEASED;
        payable(e.vendor).transfer(e.amount);
        
        emit EscrowEscalated(_id, msg.sender);
        emit EscrowReleased(_id, e.vendor, e.amount);
        emit AuditEvent(msg.sender, "ESCROW_ESCALATED", _id);
    }

    // ─── Internal Helpers ─────────────────────────────────────────────────
    function recoverSigner(bytes32 _ethSignedMessageHash, bytes memory _signature) internal pure returns (address) {
        require(_signature.length == 65, "invalid signature length");
        bytes32 r; bytes32 s; uint8 v;
        assembly {
            r := mload(add(_signature, 32))
            s := mload(add(_signature, 64))
            v := byte(0, mload(add(_signature, 96)))
        }
        return ecrecover(_ethSignedMessageHash, v, r, s);
    }
}
