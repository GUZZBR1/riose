# RIOSE isometric farm demo

The `/demo` page mounts a transparent, isometric pixel-art diorama using the
existing FastAPI static site and Phaser 3.90.0. The environment is composed from
separate image layers; cows are independent, deterministic entities. The farm
scene starts without API calls or database writes. Animal records, local event
verification and optional Solana Devnet actions remain available from the
selected-animal card.

## Build and checks

```sh
npm ci
npm test
```

For browser checks and captures, install the pinned Playwright Chromium runtime
once and start the FastAPI app on port 8009, then run:

```sh
npx playwright install chromium
npm run test:e2e
```

`npm run build` writes the frontend bundle to
`src/riose/products/livestock_tracking/adapters/static/assets/farm-demo/farm-demo.js`.

## Scene structure

- `src/FarmScene.ts`: independent scene lifecycle, entities and selection.
- `src/environment/FarmEnvironmentLayer.ts`: individually positioned terrain,
  path, water, barn, fence, tree and prop sprites.
- `src/entities/CowEntity.ts`: photo-independent pixel-art cow entities with
  pointer selection, direction changes and a restrained walking gait.
- `src/simulation/behavior.ts`: per-animal deterministic navigation and
  grazing/walking/resting state machine. Movement starts automatically and
  reduced-motion preferences keep animal positions still.
- `src/simulation/farm-layout.ts`: handcrafted meadow routes and clustered
  starting positions.
- `src/camera/CameraController.ts`: quiet default framing, subtle focus and
  optional drag/wheel navigation without visible controls.
- `tools/prepare_iso_assets.py`: crops and pixelizes the original reusable art
  sources into independent runtime assets.

There are 24 cows by default and a supported limit of 100 for performance
checks. Select cows by clicking, tapping or focusing the scene and using arrow
keys. The selected card uses the existing realistic generated animal portrait;
the cows in the diorama remain pixel art.

## Replacing art

Keep `assets-source/isometric/` as the editable source art set. The island,
path, pond, barn, foliage, props, fences and cattle are separate transparent
images. Run `python3 tools/prepare_iso_assets.py` from this directory to rebuild
`src/riose/products/livestock_tracking/adapters/static/assets/farm-demo/isometric/`.
To replace a sprite, preserve its output filename or update the asset manifest
and corresponding placements in `FarmEnvironmentLayer.ts`. Update pasture
waypoints in `farm-layout.ts` only if a new composition changes walkable space.

The diorama cows begin grazing, resting and walking asynchronously. The detail
screen still uses the existing API for animal history and its integrity check;
an optional asset creation requires wallet approval and Devnet verification.
