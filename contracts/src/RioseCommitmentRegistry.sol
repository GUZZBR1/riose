// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice Anchors a RIOSE canonical commitment without publishing Event V1 data.
/// @dev Uniqueness is local to this deployment; the same commitment may be
///      registered on another network or registry.
contract RioseCommitmentRegistry {
    error ZeroCommitment();
    error AlreadyRegistered(bytes32 commitment);
    error UnauthorizedPublisher();
    error InvalidPublisher();

    event CommitmentRegistered(bytes32 indexed commitment, address indexed publisher);

    // One storage slot per commitment makes duplicate rejection durable. Block
    // time and publisher remain available through the transaction's event log.
    mapping(bytes32 => bool) public registered;
    address public immutable publisher;

    constructor(address authorizedPublisher) {
        if (authorizedPublisher == address(0)) revert InvalidPublisher();
        publisher = authorizedPublisher;
    }

    function register(bytes32 commitment) external {
        if (msg.sender != publisher) revert UnauthorizedPublisher();
        if (commitment == bytes32(0)) revert ZeroCommitment();
        if (registered[commitment]) revert AlreadyRegistered(commitment);

        registered[commitment] = true;
        emit CommitmentRegistered(commitment, msg.sender);
    }
}
