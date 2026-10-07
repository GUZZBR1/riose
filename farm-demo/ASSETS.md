# RIOSE farm demo art assets

Regenerate the atlases, pixelated diorama and Tiled map with:

```sh
python3 tools/generate_assets.py
```

The generator is deterministic. It uses hand-authored Pillow tile/sprite drawing,
fixed palettes and the source illustration in `assets-source/` for the diorama.
All map coordinates are 32 px per tile.

## Map and tile atlas

- `farm-map.json`: orthogonal Tiled map, 64 × 44 tiles (2048 × 1408 world pixels), storing the meadow, winding paths, fence zones, landmarks and anchor coordinates.
- Tile layers are ordered `ground`, `paths`, `fences`, `details`; `landmarks` contains the barn, trees, pond and shed; `anchors` contains four fixed receiver-anchor locations.
- `farm-tiles.png`: 384 × 256 px, 12 columns × 8 rows, each atlas tile is 32 × 32 px.
- `diorama.png`: 2048 × 1408 px, 64-color pixelated world illustration used as the visible environment. `FarmScene` layers interactive animals and mode overlays above it; the Tiled map remains the coordinate source for entities and anchors.
- Tiled `firstgid` is 1, so atlas index `n` is map GID `n + 1`; zero means transparent/empty.

Atlas indices (zero-based):

| Index | Contents |
|---:|---|
| 0–7 | Meadow ground textures and grass variations |
| 8–23 | Curved dirt path autotile set |
| 24–39 | Fence autotile set with corners, ends and gates |
| 40–55 | Flowers, stones, hay and small farm props |
| 56–95 | Reserved for authored environmental variations |

The source illustration is a generated 1536 × 1024 image in
`assets-source/organic-farm-diorama.png`; the build process reduces it to a
64-color pixel palette and scales it with nearest-neighbour sampling. Replace
that source to re-art-direct the scene while keeping the map coordinates,
animal behavior, anchors and interaction code intact.

## Cattle atlas

- `cattle-atlas.png`: 512 × 320 px, 16 columns × 10 rows of 32 × 32 px frames (160 frames).
- Each coat has 4 facings × 5 actions × 2 animation frames.
- Frame index: `(((coat * 4 + direction) * 5 + action) * 2 + frame)`; pixel origin is `((index % 16) * 32, floor(index / 16) * 32)`.
- Coat order: black/white, red, cream, dark. Direction order: north, east, south, west. Action order: idle, graze, walk, drink, turn. Frames are 0 and 1.
- Small ochre ear tags are part of each animal sprite.
