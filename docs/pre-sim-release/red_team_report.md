# Independent red-team report

Candidate: 64846b0b6182cc0b248fe453dd875e0170c5a929

The accepted subset was inspected for Event V1 and Commitment V1 regressions, SEC-SOLANA-001, private-data handling, wallet/signing, public-chain claims, retries, simulation labels, and restoration of virtual-fence behavior. No tokenization endpoint, signer, wallet integration, or false public confirmation path is in the candidate snapshot. Simulation and identity preview remain explicitly illustrative; public testnets remain unverified.

PR #41 findings are excluded: unauthenticated animal-asset read/mutation APIs (P1), release/signature persistence race and duplicate-mint exposure (P2), insufficient exact transaction proof before Devnet confirmation (P2), and mutable HTTP metadata promoted as an anchoring digest without immutable comparison (P2). Earlier removal of virtual-fence behavior is also excluded and restored.

The inherited contracts test-only dependency audit reports 9 advisories (1 critical, 7 high, 1 moderate) in local Ganache/solc tooling; this is recorded as a follow-up risk. No branch or worktree cleanup has run.

Read-only final review found no new P0/P1 in the candidate; the excluded PR delta adds the mutable-digest P2 described above. A second delegated reviewer could not run because of model/usage limits; this report is a completed self-audit with explicit evidence boundaries.

## Published-tree manifest finding and repair

Independent final review found one P2 evidence-integrity defect in published SHA `1f689a806bbf5921a2b7a4605fa28b989416ea43`: `security/manifest.json` listed a stale digest and byte count for `security/discovery.json`. The manifest entry is corrected to SHA-256 `33060cf85ce03bfc9d333607a18d8dc0cde27284e368c0f77edd75b551414590`, 7,345 bytes. PR_FAST passed (85), scientific tests passed (315, 1 expected skip), and the security-focused regression passed (179, 1 expected skip) after the correction. No additional P0/P1/P2 source finding was identified. This correction is pending non-force republication and final remote CI observation.
