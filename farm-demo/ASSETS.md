# RIOSE farm demo art assets

Regenerate every PNG and the Tiled map with:

```sh
python3 tools/generate_assets.py
```

The generator is deterministic and uses hand-authored Pillow drawing primitives, fixed palettes and a fixed map layout. All dimensions are in pixels; map coordinates are 32 px per tile.

## Map and tile atlas

- `farm-map.json`: orthogonal Tiled map, 48 × 32 tiles (1536 × 1024 world pixels).
- Tile layers are ordered `ground`, `paths`, `structures`; an `anchors` object layer contains four fixed receiver-anchor locations.
- `farm-tiles.png`: 256 × 128 px, 8 columns × 4 rows, each atlas tile is 32 × 32 px.
- Tiled `firstgid` is 1, so atlas index `n` is map GID `n + 1`; zero means transparent/empty.

Atlas indices (zero-based):

| Index | Contents |
|---:|---|
| 0–3 | Continuous grass base with subtle authored flecks |
| 4–6 | Dirt path center and edge variants |
| 7 | Water surface |
| 8–11 | Horizontal fence, vertical fence, corner, gate |
| 12–15 | Tree canopy variations and shrub |
| 16–18 | Barn roof, entrance facade, modular wall |
| 19 | Water trough |
| 20 | Receiver anchor marker |
| 21 | Hay stack |
| 22 | Utility box/pump |
| 23 | Transparent reserved tile |

## Cattle atlas

- `cattle-atlas.png`: 512 × 320 px, 16 columns × 10 rows of 32 × 32 px frames (160 frames).
- Each coat has 4 facings × 5 actions × 2 animation frames.
- Frame index: `(((coat * 4 + direction) * 5 + action) * 2 + frame)`; pixel origin is `((index % 16) * 32, floor(index / 16) * 32)`.
- Coat order: black/white, red, cream, dark. Direction order: north, east, south, west. Action order: idle, graze, walk, drink, turn. Frames are 0 and 1.
- Small ochre ear tags are part of each animal sprite.
