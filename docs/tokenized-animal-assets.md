# Tokenized animal assets (product analysis)

## User requirement

Create a unique digital token asset for each individual bovine. The token should
identify one animal in the product experience. The requested chain is Solana.
The first demo implementation uses one Metaplex Core Asset per bovine on
Devnet; it does not mint one token per event, telemetry sample, or arbitrary
database element. Devnet is the implementation default for the demo, not a
production network decision.

## Reconcile with the current fork scope

The current `guzzbr1/main` candidate explicitly excludes general publication
and blockchain integration. See §5 of
[`RIOSE_INTEGRATION_CANDIDATE_REPORT.md`](../RIOSE_INTEGRATION_CANDIDATE_REPORT.md),
the `DO_NOT_INTEGRATE` policy in
[`RIOSE_INTEGRATION_PROVENANCE.json`](../RIOSE_INTEGRATION_PROVENANCE.json), and
the event/evidence row in
[`INTELLIGENCE_RESEARCH_INTEGRATION_PACKET.md`](../INTELLIGENCE_RESEARCH_INTEGRATION_PACKET.md).
The user's later, explicit request adds a narrow capability: one tokenized
asset per bovine. It does not reopen general publication of event history,
telemetry, sensor outputs, or arbitrary animal records.

## Current implementation status

The accepted tree did not mint animal tokens or show a tokenization flow. Its
product report excludes general blockchain publication, which remains out of
scope. The narrow per-animal flow has a private SQLite intent/submission
registry, a generic public metadata endpoint, and a browser module using the
Metaplex Core SDK and a Phantom wallet adapter. The status remains
`SUBMITTED_UNVERIFIED` on the server; the browser verifies the Solana Devnet
signature, Core instruction, owner, URI, and account before showing
`VALIDATED_ON_DEVNET`. Browser storage keeps an in-flight asset address so the
module can recover a transaction if the RPC response or page is interrupted;
it also takes an origin-wide mint lock. SQLite reserves the per-animal slot
before the wallet transaction, preventing concurrent clients from creating two
assets for the same bovine. A confirmed wallet rejection releases only that
unsigned reservation. The backend only resets a submitted asset after Devnet
confirms that its transaction failed.
The `/demo` interface offers asset creation as an explicit optional step after
the simulation and local event-chain demonstration. No wallet connection is
needed to complete the main product story.

## Product and architecture boundaries

- Keep each animal's identity-to-asset mapping in the product's private local
  persistence boundary. Never send local animal IDs, ear-tag IDs, owners, farm
  locations, health/veterinary records, telemetry, or event payloads as token
  metadata.
- Keep any future animal-asset creation/ownership interface distinct from
  event-history integrity. A local hash chain detects changes to recorded data;
  it does not mint an asset or establish physical identity or legal ownership.
- Do not add blockchain publication for event history as part of this feature.
- [Metaplex Core](https://www.metaplex.com/docs/smart-contracts/core/what-is-an-asset)
  is the selected demo standard after comparing its one-account asset model to
  classic Token Metadata. The official guide recommends Core for new NFT
  projects and documents wallet-signed asset creation.
- Minting must use a connected browser wallet; the application must never hold
  a wallet secret. The user must initiate each mint and approve the transaction.
- Metadata remains a strict public allowlist: generic asset name/description
  and RIOSE artwork only. No local animal ID, hardware/ear-tag ID, owner, farm,
  location, health, telemetry, or event data. Do not add animal-specific public
  traits unless the user approves their disclosure.
- A submitted transaction is not a confirmed token. Keep status
  `SUBMITTED_UNVERIFIED` until a chain read verifies the Core asset address,
  owner, metadata URI, cluster, and signature. Never label a preview as minted.
- No production transfer policy, legal title, mainnet deployment, or collection
  authority is implied by this demo. A Solana asset is not proof of physical
  animal identity or legal ownership.

## Design boundary

[`DESIGN.md`](../DESIGN.md) defines RIOSE's visual system: a quiet hardware
research project centered on the ear tag. It keeps the landing page minimal and
explicitly says not to add promotional cards or sections there. The API serves
`landing.html` at `/`, `manifesto.html` at `/manifesto`, and the product story
at `index.html` on `/demo` (`adapters/api.py`). The demo reuses the existing tag
viewer and uses an SVG schematic for simulated receiver activity.

The existing API exposes local animals, events, behaviors, and tracking data.
The tokenization flow adds a separate private animal-to-asset registry and does
not treat event integrity as proof of an on-chain token. Its backend endpoints
are `/api/animals/{animal_id}/asset-intent`,
`/api/animals/{animal_id}/asset-reserve`,
`/api/animals/{animal_id}/asset-release`,
`/api/animals/{animal_id}/asset-submission`,
`/api/animals/{animal_id}/asset`,
`/api/animals/{animal_id}/asset-reconcile`, and
`/api/animal-assets/metadata/{public_ref}`. JavaScript source and npm build
configuration are in `web3-demo/`; the generated ESM bundle is served from the
existing static assets directory.

## Research limitation

An NFT by itself does not establish that the physical bovine exists, validate
its source records, or adjudicate legal ownership. Public metadata and URIs are
persistent; a stable hash may still be correlated and is not automatically
anonymous.
