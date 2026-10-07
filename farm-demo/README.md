# RIOSE farm demo

The `/demo` page mounts a TypeScript + Phaser 3.90 scene inside the existing
FastAPI static site. The scene is client-only and deterministic; it does not
call the simulation API or write farm motion into SQLite.

## Build and checks

```sh
npm ci
npm test
```

For the optional browser walkthrough and captures, install the pinned Playwright
Chromium runtime once, then run `npm run test:e2e` from this directory:

```sh
npx playwright install chromium
npm run test:e2e
```

`npm run build` writes the browser bundle to
`src/riose/products/livestock_tracking/adapters/static/assets/farm-demo/farm-demo.js`.
The static server already mounts that directory at `/assets`.

## Scene structure

- `src/FarmScene.ts`: tilemap loading, anchors, entity lifecycle and visual modes.
- `src/entities/CowEntity.ts`: pixel-art sprite, selection and render state.
- `src/simulation/behavior.ts`: repeatable per-animal movement/state schedule.
- `src/simulation/farm-layout.ts`: pasture waypoints and qualitative local signal bands.
- `src/camera/CameraController.ts`: overview, track focus, drag pan and zoom.
- `tools/generate_assets.py`: reproducible, hand-authored pixel assets and map.

The scene creates 24 animals by default and accepts `animalCount` up to 100 for
performance testing. Human-readable labels are `Animal 0` through `Animal N`;
the internal keys are client demo keys rather than product tag IDs.

## Replace the art

Keep the current image paths and frame contract, or update them together with
the matching TypeScript loader. `farm-map.json` is an orthogonal Tiled map with
32 px tiles and `ground`, `paths`, `structures` and `anchors` layers. The tiles
are in `assets/farm-demo/farm-tiles.png`; the cow atlas is four coats × four
directions × five actions × two frames in
`assets/farm-demo/cattle-atlas.png`. Frame indices are documented in
`assets/farm-demo/README.md`. Re-run `python3 tools/generate_assets.py` from this
directory to regenerate the checked-in source assets deterministically.

The compact farm panel labels scene values `SIMULATED` / `ESTIMATED`. The
separate animal record still uses the existing API, local event-chain check and
optional Solana Devnet flow.
