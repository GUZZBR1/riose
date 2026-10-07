# Colosseum product-demo requirements

Research checked on 2026-10-06. Confirm the selected competition and deadline
inside Colosseum before submitting.

## Competition format

- The [Crypto World's Fair event page](https://colosseum.com/worldsfair) lists
  the event through October 12, 2026, and a dedicated Solana ecosystem track.
- Colosseum's [Fall 2026 hackathon FAQ](https://colosseum.com/hackathon?year=fall2026)
  requests a separate two-to-three-minute presentation video and a product
  demo video no longer than three minutes.
- The demo should show the working product. The presentation should explain
  the opportunity, execution, market, viability, and founder insight without
  turning the product demo into a slide or code walkthrough.
- The FAQ permits existing code but asks applicants to disclose work that
  predates the competition. Keep the project history and this disclosure
  accurate in the application.

## RIOSE demo story

The `/demo` path opens on a client-side simulated farm. A short product walkthrough can:

1. See the paddocks, herd, paths and anchors immediately, with deterministic ambient movement.
2. Switch between Overview, Signals, Coverage and Track, then select an animal for its compact status panel.
3. Open its complete narrative and verify the local event history.
4. Optionally connect a wallet and create the generic animal asset on Solana
   Devnet. Show a confirmed state only after reading and verifying the asset
   from Devnet.

Simulation outputs are not physical RF reception. A local hash-chain check
shows the integrity of locally recorded events; it does not establish physical
identity or blockchain publication. Public asset metadata excludes animal,
tag, owner, farm, location, health, telemetry, and event data.

The product path should fit within three minutes. The `/` landing and
`/manifesto` stay intact; the landing header links to `/demo`, and the interactive
3D tag remains on the central landing page. The farm uses a deterministic local
scene and clearly distinguishes estimated scene values from hash-verified local
records. Simulated movement is not written into the API or database.

## Sources

- [Crypto World's Fair event and Solana track](https://colosseum.com/worldsfair)
- [Official Fall 2026 hackathon FAQ](https://colosseum.com/hackathon?year=fall2026)
