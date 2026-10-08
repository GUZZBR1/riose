# Isometric farm art assets

Editable generated source layers are in `assets-source/isometric/`. Each layer
uses a consistent isometric view and transparent background. Runtime sprites
are individual PNGs in
`src/riose/products/livestock_tracking/adapters/static/assets/farm-demo/isometric/`.

Rebuild the runtime assets with:

```sh
python3 tools/prepare_iso_assets.py
```

The preparation script crops the six-sprite foliage, prop, fence and cattle
atlases, normalizes alpha and palette, and writes each sprite separately. The
island base, winding path, pond/creek and barn are already separate source
layers. This keeps all scene elements replaceable without flattening the whole
farm or baking in the interactive cows.

`FarmEnvironmentLayer.ts` is the runtime asset manifest and composition: it
positions each background/environment sprite, while `CowEntity.ts` creates
independent selectable cattle. Keep the same filenames to swap art without
changing entity logic. If art dimensions or walkable areas change, update sprite
display sizes and meadow waypoints in the matching TypeScript modules.
