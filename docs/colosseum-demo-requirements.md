# Colosseum product-demo requirements

Research checked on 2026-10-06. This brief captures submission constraints; it
does not prescribe product copy or visual design.

## Event and deadline

- The current [Crypto World's Fair event page](https://colosseum.com/worldsfair)
  lists the competition as live from September 14 to October 12, 2026.
- The event has a dedicated Solana ecosystem track. The event page lists a
  $100,000 track pool split across ten projects.
- Colosseum's [Fall 2026 hackathon FAQ](https://colosseum.com/hackathon?year=fall2026)
  asks for two separate videos: a two-to-three-minute presentation and a
  product-demo video no longer than three minutes.
- The separate [2026 schedule announcement](https://blog.colosseum.com/2026-hackathons-updraft-course-offline-signer-cli/)
  lists a Fall Solana hackathon from September 28 to November 2. This differs
  from the live Crypto World's Fair dates. The user-provided application prompt
  naming a product demo and YouTube/Loom/Vimeo matches the current FAQ; confirm
  the selected event inside the submission portal before relying on a deadline.

## Demo constraints supplied by the user

- Maximum duration: three minutes.
- Show the working product in the live experience.
- No slide deck and no code walkthrough.
- Video host: YouTube, Loom, or Vimeo.

## Product constraints from this fork and the user's request

- The accepted `guzzbr1/main` tree removes general blockchain publication as
  out of scope; the user has now explicitly requested one tokenized asset for
  each bovine. Implement that bounded asset flow without bringing back generic
  publication of animal events or telemetry.
- The current accepted tree does not mint those assets. Do not call a local
  preview or simulated interaction an on-chain mint.
- The product and visual rules remain in [`DESIGN.md`](../DESIGN.md). The
  landing page stays minimal; a demo should not be added as a promotional card
  or new sales section in the landing hero.
- The final demo interaction and wording must follow the user's forthcoming
  visual references; this document deliberately does not invent either.

## Sources

- [Crypto World's Fair event and Solana track](https://colosseum.com/worldsfair)
- [Official Fall 2026 hackathon FAQ](https://colosseum.com/hackathon?year=fall2026)
- [Colosseum's 2026 schedule announcement](https://blog.colosseum.com/2026-hackathons-updraft-course-offline-signer-cli/)
- The three-minute, live-product and supported-host constraints above also
  reflect the application prompt supplied directly by the user.
