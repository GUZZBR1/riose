# RIOSE

### Every animal leaves a signal.

An ear tag gives each animal a consistent identity. RIOSE uses that identity to organize an animal's record across the farm, then gives the record a path to verifiable digital proof.

<img align="right" width="280" src="docs/readme/assets/ear-tag-cutout.png" alt="RIOSE ear-tag product concept, isolated on a transparent background">

The tag is the starting point: it gives the record a subject. The animal's events and private farm information remain in the RIOSE application; a public proof can be created without putting that history on-chain.

[Explore the interactive demo](#run-the-demo)

<br clear="right">

<table>
  <tbody>
    <tr>
      <td width="52%" valign="middle">
        <h2>One workflow, across two farms</h2>
        <p>Farms do not all look or operate the same way. The demo pairs a lush pasture with an open Cerrado ranch to show the same individual-animal workflow in two different environments.</p>
        <p>The landscape changes—from water and dense greenery to open grassland and warmer soil—but the product stays focused on an identifiable animal and its record.</p>
      </td>
      <td width="48%" valign="middle">
        <img src="docs/readme/assets/connected-farms-concept.png" alt="Concept art connecting a lush dairy farm and an open Cerrado cattle ranch">
        <p align="center"><sub>Two farm environments, one product direction</sub></p>
      </td>
    </tr>
    <tr>
      <td width="48%" valign="middle">
        <img src="docs/readme/assets/riose-homepage-concept.jpg" alt="Early RIOSE website cover concept, featuring a cow and the product experience">
        <p align="center"><sub>Early RIOSE homepage concept</sub></p>
      </td>
      <td width="52%" valign="middle">
        <h2>Bring one animal into focus</h2>
        <p>The experience starts with the farm. Select an animal and its identity and record come into focus beside the scene, keeping the animal, its environment, and its individual history connected.</p>
        <p>The image is an early concept for the website's welcome. In the <a href="#run-the-demo">interactive demo</a>, animal movement and location are part of the browser experience, not a live feed from deployed tags.</p>
      </td>
    </tr>
  </tbody>
</table>

## Turn a record into verifiable proof

The animal's operational record stays in RIOSE. When someone needs to compare a known record with a shared proof, RIOSE can create a cryptographic digest and anchor that digest on Solana.

<p align="center"><strong>Animal identity → Farm record → Digest → Solana anchor</strong></p>

1. **Identify** — associate an animal profile with its ear-tag identity.
2. **Record** — keep an ordered history of events in the local application.
3. **Create a digest** — derive a canonical SHA-256 commitment from the record.
4. **Anchor when needed** — publish the digest through the Solana Memo path; the event history and private farm data stay off-chain.

A confirmed commitment lets someone compare a known record with its digest. It does not establish that an event happened, prove physical animal identity, or transfer ownership.

## Research inspiration

RIOSE's direction is informed by research into animal-specific sensing. One reference is [*Machine learning-assisted self-powered ear tag for animal welfare*](https://www.nature.com/articles/s41467-026-73651-7), published in *Nature Communications* in 2026. That paper explores self-powered biochemical sensing; RIOSE's current software focuses on animal identity, event records, and verifiable commitments.

## Run the demo

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
./scripts/bootstrap.sh
uv run --locked cattle-rf demo --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/demo> to explore the farm experience. The local service also exposes the livestock API at the root and the RF simulator at `/simulator`.

<details>
  <summary>Repository details and validation scope</summary>

- **Livestock application:** animal profiles, Event V1 history, SQLite persistence, and an offline-first publication outbox.
- **Farm experience:** two interactive, illustrative farm scenes with selectable animals and contextual profiles.
- **Ear-tag engineering:** firmware models, RF simulation, localization research, and digital-twin tooling.
- **Verification software:** canonical commitments, a Solana Memo adapter, and an EVM registry/test harness.

The software paths have local automated coverage. Public-chain publication and physical field validation have not been independently verified; the browser farm and RF outputs are simulations or models. See the [integrated beta evidence](docs/reports/INTEGRATED_BETA_COMPLETION_GATE.md), [multichain evidence](docs/reports/MULTICHAIN_MAIN_RECONCILIATION_DOD.md), and [reproducible validation guide](reproducibility/README.md) for scope and results.

For implementation details, start with [`src/riose/products/livestock_tracking/`](src/riose/products/livestock_tracking/) and [`src/riose/products/ear_tag/`](src/riose/products/ear_tag/).

</details>
