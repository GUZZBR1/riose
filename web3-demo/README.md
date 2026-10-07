# RIOSE animal asset module

This browser module creates one Metaplex Core Asset for one registered bovine
on Solana Devnet. It uses the connected Phantom wallet for signing and payment;
the application never receives a wallet secret. The module is ready to be
connected to `/demo` after the visual references and product wording are set.
Before asking the wallet to sign, the API reserves that bovine's single Devnet
asset slot; duplicate clients receive a conflict while that attempt is open.

Build the static ESM bundle from this directory:

```sh
npm ci
npm run build
```

The generated file is served by FastAPI at
`/assets/animal-tokenization.bundle.js`. Metadata is generic and served by the
RIOSE API. A public deployment needs a reachable HTTPS origin before its URI is
minted into a Devnet asset. Keep the intent/submission API status as
`SUBMITTED_UNVERIFIED`; only a successful RPC read of the transaction and Core
asset returns `VALIDATED_ON_DEVNET` in the browser.
