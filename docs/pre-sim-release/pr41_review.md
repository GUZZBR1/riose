# PR #41 review

- Current head: c8f4c62cf603dac04623f6f54dbb250784d5752f; advanced from previously reviewed 129f19a55e7b29c9e70e1cb9cea78ab3f14d9bc0.
- Source: santleme/riose, branch codex/tokenized-animal-demo; author santleme; base GUZZBR1/riose main.
- GitHub refresh: OPEN, not draft, mergeable/clean; core and cad-export checks succeeded; zero reviews and zero issue comments. Mergeability is only a Git signal.
- Verdict: PARTIALLY_INTEGRATE; do not merge original PR directly.

## Capabilities and architecture

The PR adds a Phaser/TypeScript isometric farm diorama, deterministic animal movement, two scenes, selection and local event readback, accessible/responsive controls, and a 100-animal browser scenario. It also adds a per-animal Solana Metaplex identity mint path with wallet UX, API reservations and metadata, backend persistence, and generated demo media. The latest head adds a guided Solana identity flow and public digest/tag metadata. Earlier commits remove virtual-fence API/tests.

Animal-asset endpoints are unauthenticated and disclose animal-linked wallet/address/attempt identifiers; mutations can create, reserve, release, and submit intents. Release can race a chain mint before the signature is durable. Browser verification does not prove the exact reserved asset creation transaction. The latest head also presents a digest from mutable HTTP metadata as an on-chain proof without comparing it with an immutable reserved/minted value, so metadata changes can leave a stale VALIDATED_ON_DEVNET claim. These are P1/P2 issues. The asset path also competes with canonical Event V1 to Commitment V1 to publication adapters. Identity must remain separate from commitment anchoring.

The accepted candidate has no wallet connection, signing, mint action, asset API, or public-chain claim. It labels movement/location simulated and keeps the existing RF simulator and fence at /simulator. No private farm, owner, health, telemetry, or precise location data is sent to a chain.

See pr41_component_matrix.json for per-component disposition. Farm demo install and 22 tests plus typecheck/build passed. Browser E2E passed on the reconciled preview candidate (desktop/mobile, API unavailable, keyboard/accessibility, 100 animals, no wallet/asset calls). Current PR checks core and cad-export were green at refresh. web3-demo build passed but is excluded; its install reported 12 moderate advisories.
