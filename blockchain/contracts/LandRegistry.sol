// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title LandRegistry - Blockchain Land Registry System
/// @notice Handles property registration, ownership transfer, and history tracking
/// @dev Government authority signs all transactions

contract LandRegistry {

    // ─────────────────────────────────────────
    // STRUCTS
    // ─────────────────────────────────────────

    struct Property {
        uint256 propertyId;
        address currentOwner;
        string  propertyAddress;
        uint256 price;
        bool    isVerified;
        bool    isDisputed;
        uint256 createdAt;
        uint256 updatedAt;
    }

    struct Transaction {
        uint256 transactionId;
        uint256 propertyId;
        address sender;
        address receiver;
        uint256 price;
        uint256 timestamp;
        string  txType;   // "REGISTER" | "TRANSFER" | "VERIFY" | "DISPUTE"
    }

    struct AuditRecord {
        uint256 propertyId;
        uint256 transactionIndex;
        bytes32 currentDataHash;
        bytes32 previousDataHash;
        bytes32 blockFingerprint;
        uint256 timestamp;
        address actor;
        string action;
    }

    // ─────────────────────────────────────────
    // STATE
    // ─────────────────────────────────────────

    address public governmentAuthority;

    mapping(uint256 => Property)       public properties;
    mapping(uint256 => Transaction[])  public propertyTransactions;
    mapping(uint256 => AuditRecord[])  private propertyAuditTrail;
    mapping(address => uint256[])      public ownerProperties;   // wallet → list of propertyIds

    uint256 public totalProperties;
    uint256 public totalTransactions;

    // ─────────────────────────────────────────
    // EVENTS
    // ─────────────────────────────────────────

    event PropertyRegistered(
        uint256 indexed propertyId,
        address indexed owner,
        string  propertyAddress,
        uint256 price,
        uint256 timestamp
    );

    event PropertyTransferred(
        uint256 indexed propertyId,
        address indexed from,
        address indexed to,
        uint256 price,
        uint256 timestamp
    );

    event PropertyVerified(
        uint256 indexed propertyId,
        uint256 timestamp
    );

    event DisputeRaised(
        uint256 indexed propertyId,
        address indexed raisedBy,
        uint256 timestamp
    );

    event DisputeResolved(
        uint256 indexed propertyId,
        uint256 timestamp
    );

    event AuditRecordStored(
        uint256 indexed propertyId,
        uint256 indexed transactionIndex,
        bytes32 currentDataHash,
        bytes32 previousDataHash,
        bytes32 blockFingerprint,
        string action
    );

    // ─────────────────────────────────────────
    // MODIFIERS
    // ─────────────────────────────────────────

    modifier onlyGovernment() {
        require(
            msg.sender == governmentAuthority,
            "Only government authority can perform this action"
        );
        _;
    }

    modifier propertyExists(uint256 propertyId) {
        require(
            properties[propertyId].propertyId != 0,
            "Property does not exist"
        );
        _;
    }

    modifier notDisputed(uint256 propertyId) {
        require(
            !properties[propertyId].isDisputed,
            "Property is under dispute"
        );
        _;
    }

    // ─────────────────────────────────────────
    // CONSTRUCTOR
    // ─────────────────────────────────────────

    constructor() {
        governmentAuthority = msg.sender;
    }

    // ─────────────────────────────────────────
    // REGISTER PROPERTY
    // ─────────────────────────────────────────

    function registerProperty(
        uint256 propertyId,
        string  memory propertyAddress,
        uint256 price,
        address ownerAddress
    ) public onlyGovernment {

        require(
            properties[propertyId].propertyId == 0,
            "Property already registered"
        );
        require(ownerAddress != address(0), "Invalid owner address");
        require(price > 0, "Price must be greater than 0");

        properties[propertyId] = Property({
            propertyId:      propertyId,
            currentOwner:    ownerAddress,
            propertyAddress: propertyAddress,
            price:           price,
            isVerified:      true,
            isDisputed:      false,
            createdAt:       block.timestamp,
            updatedAt:       block.timestamp
        });

        // Record genesis transaction
        propertyTransactions[propertyId].push(Transaction({
            transactionId: 1,
            propertyId:    propertyId,
            sender:        governmentAuthority,
            receiver:      ownerAddress,
            price:         price,
            timestamp:     block.timestamp,
            txType:        "REGISTER"
        }));

        ownerProperties[ownerAddress].push(propertyId);
        _appendAuditRecord(
            propertyId,
            ownerAddress,
            price,
            "REGISTER",
            governmentAuthority
        );

        totalProperties++;
        totalTransactions++;

        emit PropertyRegistered(
            propertyId,
            ownerAddress,
            propertyAddress,
            price,
            block.timestamp
        );
    }

    // ─────────────────────────────────────────
    // TRANSFER PROPERTY
    // ─────────────────────────────────────────

    function transferProperty(
        uint256 propertyId,
        address newOwner,
        uint256 price
    )
        public
        onlyGovernment
        propertyExists(propertyId)
        notDisputed(propertyId)
    {
        require(newOwner != address(0), "Invalid new owner address");
        require(price > 0, "Price must be greater than 0");

        Property storage prop = properties[propertyId];
        address previousOwner = prop.currentOwner;

        require(previousOwner != newOwner, "New owner is same as current owner");

        // Remove from previous owner list
        _removeFromOwnerList(previousOwner, propertyId);

        // Update property
        prop.currentOwner = newOwner;
        prop.price        = price;
        prop.updatedAt    = block.timestamp;

        // Record transfer transaction
        uint256 txId = propertyTransactions[propertyId].length + 1;

        propertyTransactions[propertyId].push(Transaction({
            transactionId: txId,
            propertyId:    propertyId,
            sender:        previousOwner,
            receiver:      newOwner,
            price:         price,
            timestamp:     block.timestamp,
            txType:        "TRANSFER"
        }));

        ownerProperties[newOwner].push(propertyId);
        _appendAuditRecord(
            propertyId,
            newOwner,
            price,
            "TRANSFER",
            governmentAuthority
        );

        totalTransactions++;

        emit PropertyTransferred(
            propertyId,
            previousOwner,
            newOwner,
            price,
            block.timestamp
        );
    }

    // ─────────────────────────────────────────
    // RAISE DISPUTE
    // ─────────────────────────────────────────

    function raiseDispute(uint256 propertyId)
        public
        onlyGovernment
        propertyExists(propertyId)
    {
        properties[propertyId].isDisputed  = true;
        properties[propertyId].updatedAt   = block.timestamp;

        propertyTransactions[propertyId].push(Transaction({
            transactionId: propertyTransactions[propertyId].length + 1,
            propertyId:    propertyId,
            sender:        governmentAuthority,
            receiver:      address(0),
            price:         0,
            timestamp:     block.timestamp,
            txType:        "DISPUTE"
        }));
        _appendAuditRecord(
            propertyId,
            properties[propertyId].currentOwner,
            properties[propertyId].price,
            "DISPUTE",
            governmentAuthority
        );

        totalTransactions++;

        emit DisputeRaised(propertyId, governmentAuthority, block.timestamp);
    }

    // ─────────────────────────────────────────
    // RESOLVE DISPUTE
    // ─────────────────────────────────────────

    function resolveDispute(uint256 propertyId)
        public
        onlyGovernment
        propertyExists(propertyId)
    {
        require(
            properties[propertyId].isDisputed,
            "Property is not under dispute"
        );

        properties[propertyId].isDisputed = false;
        properties[propertyId].updatedAt  = block.timestamp;
        _appendAuditRecord(
            propertyId,
            properties[propertyId].currentOwner,
            properties[propertyId].price,
            "RESOLVE",
            governmentAuthority
        );

        emit DisputeResolved(propertyId, block.timestamp);
    }

    // ─────────────────────────────────────────
    // READ FUNCTIONS
    // ─────────────────────────────────────────

    function getPropertyOwner(uint256 propertyId)
        public
        view
        propertyExists(propertyId)
        returns (address)
    {
        return properties[propertyId].currentOwner;
    }

    function getPropertyDetails(uint256 propertyId)
        public
        view
        propertyExists(propertyId)
        returns (Property memory)
    {
        return properties[propertyId];
    }

    function getPropertyHistory(uint256 propertyId)
        public
        view
        propertyExists(propertyId)
        returns (Transaction[] memory)
    {
        return propertyTransactions[propertyId];
    }

    function getOwnerProperties(address owner)
        public
        view
        returns (uint256[] memory)
    {
        return ownerProperties[owner];
    }

    function getPropertyAuditTrail(uint256 propertyId)
        public
        view
        propertyExists(propertyId)
        returns (AuditRecord[] memory)
    {
        return propertyAuditTrail[propertyId];
    }

    function verifyProperty(uint256 propertyId)
        public
        view
        propertyExists(propertyId)
        returns (bool isVerified, bool isDisputed, address owner)
    {
        Property memory prop = properties[propertyId];
        return (prop.isVerified, prop.isDisputed, prop.currentOwner);
    }

    function isPropertyDisputed(uint256 propertyId)
        public
        view
        propertyExists(propertyId)
        returns (bool)
    {
        return properties[propertyId].isDisputed;
    }

    // ─────────────────────────────────────────
    // INTERNAL HELPERS
    // ─────────────────────────────────────────

    function _removeFromOwnerList(address owner, uint256 propertyId) internal {
        uint256[] storage list = ownerProperties[owner];
        for (uint256 i = 0; i < list.length; i++) {
            if (list[i] == propertyId) {
                list[i] = list[list.length - 1];
                list.pop();
                break;
            }
        }
    }

    function _appendAuditRecord(
        uint256 propertyId,
        address owner,
        uint256 price,
        string memory action,
        address actor
    ) internal {
        Property memory prop = properties[propertyId];
        bytes32 previousHash = bytes32(0);
        uint256 auditLength = propertyAuditTrail[propertyId].length;

        if (auditLength > 0) {
            previousHash = propertyAuditTrail[propertyId][auditLength - 1].currentDataHash;
        }

        uint256 transactionIndex = propertyTransactions[propertyId].length;
        bytes32 currentHash = keccak256(
            abi.encode(
                propertyId,
                owner,
                prop.propertyAddress,
                price,
                prop.isVerified,
                prop.isDisputed,
                prop.createdAt,
                prop.updatedAt,
                action,
                transactionIndex
            )
        );

        bytes32 fingerprint = keccak256(
            abi.encodePacked(
                propertyId,
                transactionIndex,
                currentHash,
                previousHash,
                block.timestamp,
                block.number,
                actor,
                blockhash(block.number - 1)
            )
        );

        propertyAuditTrail[propertyId].push(
            AuditRecord({
                propertyId: propertyId,
                transactionIndex: transactionIndex,
                currentDataHash: currentHash,
                previousDataHash: previousHash,
                blockFingerprint: fingerprint,
                timestamp: block.timestamp,
                actor: actor,
                action: action
            })
        );

        emit AuditRecordStored(
            propertyId,
            transactionIndex,
            currentHash,
            previousHash,
            fingerprint,
            action
        );
    }
}
