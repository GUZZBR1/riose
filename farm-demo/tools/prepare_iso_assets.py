#!/usr/bin/env python3
"""Prepare reusable isometric art layers from the checked-in source sheets."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets-source/isometric'
OUTPUT = (ROOT.parent / 'src/riose/products/livestock_tracking/adapters/static'
          / 'assets/farm-demo/isometric')


def clean(image: Image.Image, threshold: int = 24) -> Image.Image:
    image = image.convert('RGBA')
    alpha = image.getchannel('A').point(lambda value: 0 if value < threshold else value)
    image.putalpha(alpha)
    return image


def crop_cell(image: Image.Image, col: int, row: int, cols: int = 3, rows: int = 2) -> Image.Image:
    width, height = image.size
    return crop_region(image, (col * width // cols, row * height // rows,
                               (col + 1) * width // cols, (row + 1) * height // rows))


def crop_region(image: Image.Image, bounds: tuple[int, int, int, int]) -> Image.Image:
    cell = image.crop(bounds)
    alpha = cell.getchannel('A').point(lambda value: 255 if value > 64 else 0)
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError(f'Empty sprite in region {bounds}')
    left, top, right, bottom = bbox
    padding = 14
    crop = cell.crop((max(0, left - padding), max(0, top - padding),
                      min(cell.width, right + padding), min(cell.height, bottom + padding)))

    # Atlas cells can contain small neighboring accents. Keep the main sprite
    # and its nearby shadow while dropping detached details that would float
    # when this sprite is placed independently in the scene.
    alpha = crop.getchannel('A')
    width, height = crop.size
    pixels = alpha.load()
    visited = bytearray(width * height)
    components: list[tuple[int, int, int, int, int, list[int]]] = []
    for y in range(height):
        for x in range(width):
            start = y * width + x
            if visited[start] or pixels[x, y] <= 64:
                continue
            visited[start] = 1
            stack = [start]
            points: list[int] = []
            min_x = max_x = x
            min_y = max_y = y
            while stack:
                current = stack.pop()
                points.append(current)
                px, py = current % width, current // width
                min_x, max_x = min(min_x, px), max(max_x, px)
                min_y, max_y = min(min_y, py), max(max_y, py)
                for ny in range(max(0, py - 1), min(height, py + 2)):
                    for nx in range(max(0, px - 1), min(width, px + 2)):
                        neighbor = ny * width + nx
                        if not visited[neighbor] and pixels[nx, ny] > 64:
                            visited[neighbor] = 1
                            stack.append(neighbor)
            components.append((len(points), min_x, min_y, max_x, max_y, points))

    largest = max(components, key=lambda component: component[0])
    main_bounds = largest[1:5]
    keep = Image.new('L', crop.size, 0)
    keep_pixels = keep.load()
    for size, min_x, min_y, max_x, max_y, points in components:
        gap_x = max(0, max(main_bounds[0] - max_x, min_x - main_bounds[2]))
        gap_y = max(0, max(main_bounds[1] - max_y, min_y - main_bounds[3]))
        if size < largest[0] * 0.08 and max(gap_x, gap_y) > 12:
            continue
        for index in points:
            keep_pixels[index % width, index // width] = 255
    crop.putalpha(ImageChops.multiply(alpha, keep))
    return crop


def pixelize(image: Image.Image, max_side: int, colors: int = 80) -> Image.Image:
    image = clean(image)
    width, height = image.size
    factor = min(1.0, max_side / max(width, height))
    # Downsample before palette reduction, then keep the pixel grid crisp.
    small_size = (max(1, round(width * factor)), max(1, round(height * factor)))
    alpha = image.getchannel('A').resize(small_size, Image.Resampling.LANCZOS)
    rgb = image.convert('RGB').resize(small_size, Image.Resampling.LANCZOS)
    palette = rgb.quantize(colors=colors, method=Image.Quantize.MEDIANCUT,
                           dither=Image.Dither.NONE).convert('RGB')
    result = palette.convert('RGBA')
    result.putalpha(alpha)
    return result


def save(image: Image.Image, name: str, max_side: int = 768) -> None:
    image = pixelize(image, max_side)
    image.save(OUTPUT / name, optimize=True)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    save(Image.open(SOURCE / 'island-base.png'), 'island-base.png', 1536)
    save(Image.open(SOURCE / 'winding-path.png'), 'winding-path.png', 1536)
    save(Image.open(SOURCE / 'pond-creek.png'), 'pond-creek.png', 768)
    save(Image.open(SOURCE / 'barn.png'), 'barn.png', 768)

    trees = Image.open(SOURCE / 'nature-atlas.png').convert('RGBA')
    tree_regions = (
        ('tree-oak', (0, 0, 512, 640)), ('tree-apple', (512, 0, 1024, 640)),
        ('tree-willow', (1024, 0, 1536, 640)),
        # Lower-row sprites start below the trees' hanging roots/branches.
        ('bush', (0, 640, 512, 1024)), ('flowers', (512, 640, 1024, 1024)),
        ('rocks', (1024, 640, 1536, 1024)),
    )
    for name, region in tree_regions:
        save(crop_region(trees, region), f'{name}.png', 256)

    props = Image.open(SOURCE / 'prop-atlas.png').convert('RGBA')
    for name, cell in zip(('trough', 'hay', 'gate', 'field-shed', 'water-pump', 'feed-bin'),
                          ((0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1))):
        save(crop_cell(props, *cell), f'{name}.png', 256)

    fences = Image.open(SOURCE / 'fence-atlas.png').convert('RGBA')
    for name, cell in zip(('fence-straight', 'fence-diagonal', 'fence-gate-open',
                           'fence-corner', 'fence-end', 'fence-gate-closed'),
                          ((0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1))):
        save(crop_cell(fences, *cell), f'{name}.png', 320)

    cattle = Image.open(SOURCE / 'cattle-atlas.png').convert('RGBA')
    for index, cell in enumerate(((0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1))):
        save(crop_cell(cattle, *cell), f'cow-{index}.png', 192)
    print(f'Prepared {len(list(OUTPUT.glob("*.png")))} reusable isometric art layers in {OUTPUT}')


if __name__ == '__main__':
    main()
