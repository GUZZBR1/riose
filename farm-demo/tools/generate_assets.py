#!/usr/bin/env python3
"""Generate the hand-authored RIOSE pixel-farm tiles, landmarks and Tiled map."""
from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = (Path(__file__).resolve().parents[2]
        / 'src/riose/products/livestock_tracking/adapters/static/assets/farm-demo')
SOURCE_ART = Path(__file__).resolve().parents[1] / 'assets-source/organic-farm-diorama.png'
TILE = 32
COLS, ROWS = 12, 8
W, H = 64, 44

PAL = {
    'grass': '#789465', 'grass_lit': '#86a36e', 'grass_dark': '#607c53',
    'grass_deep': '#526d4b', 'moss': '#71865b', 'cream': '#f0e8cf',
    'dirt': '#a98c66', 'dirt_light': '#c3a77b', 'dirt_shadow': '#80694d',
    'wood': '#604637', 'wood_lit': '#a5784f', 'wood_dark': '#40352e',
    'leaf': '#385e48', 'leaf_lit': '#71905a', 'leaf_warm': '#a17c4d',
    'water': '#5c9ca0', 'water_deep': '#397d86', 'water_lit': '#a7d5c0',
    'flower_yellow': '#e8c66f', 'flower_white': '#f0e8cf', 'flower_pink': '#d78472',
    'stone': '#908d77', 'shadow': '#384a39', 'tag': '#d8b64f',
}


def px(draw: ImageDraw.ImageDraw, x: int, y: int, color: str) -> None:
    draw.point((x, y), fill=color)


def grass_cell(index: int) -> Image.Image:
    im = Image.new('RGBA', (TILE, TILE), PAL['grass'])
    d = ImageDraw.Draw(im)
    patterns = [
        [(4, 8, 'grass_lit'), (8, 9, 'grass_lit'), (22, 17, 'grass_dark'), (24, 18, 'grass_dark')],
        [(7, 21, 'grass_dark'), (8, 20, 'grass_lit'), (23, 7, 'grass_lit'), (24, 8, 'grass_lit')],
        [(4, 13, 'grass_dark'), (5, 13, 'grass_dark'), (20, 22, 'grass_lit'), (22, 23, 'grass_lit')],
        [(11, 6, 'grass_lit'), (12, 7, 'grass_lit'), (26, 22, 'grass_dark'), (27, 22, 'grass_dark')],
        [(5, 24, 'grass_lit'), (6, 23, 'grass_lit'), (18, 10, 'grass_dark'), (19, 11, 'grass_dark')],
        [(13, 19, 'grass_lit'), (14, 18, 'grass_lit'), (26, 9, 'grass_dark'), (25, 10, 'grass_dark')],
        [(8, 5, 'grass_dark'), (9, 6, 'grass_dark'), (21, 24, 'grass_lit'), (22, 25, 'grass_lit')],
        [(3, 18, 'grass_lit'), (4, 19, 'grass_lit'), (16, 7, 'grass_dark'), (17, 8, 'grass_dark')],
    ][index]
    for x, y, color in patterns:
        px(d, x, y, PAL[color])
    return im


def path_cell(mask: int) -> Image.Image:
    """A transparent, soft-cornered dirt segment connected by N/E/S/W bits."""
    im = Image.new('RGBA', (TILE, TILE), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, 31, 31), radius=7, fill=PAL['dirt_shadow'])
    d.rounded_rectangle((0, 0, 29, 29), radius=7, fill=PAL['dirt'])
    if mask & 1: d.rectangle((7, 0, 24, 16), fill=PAL['dirt'])
    if mask & 2: d.rectangle((16, 7, 31, 24), fill=PAL['dirt'])
    if mask & 4: d.rectangle((7, 16, 24, 31), fill=PAL['dirt'])
    if mask & 8: d.rectangle((0, 7, 16, 24), fill=PAL['dirt'])
    d.line((4, 5, 17, 5), fill=PAL['dirt_light'], width=1)
    for x, y, color in ((7, 14, 'dirt_light'), (19, 8, 'dirt_light'),
                        (23, 19, 'dirt_shadow'), (12, 23, 'dirt_shadow')):
        px(d, x, y, PAL[color])
    return im


def fence_cell(mask: int) -> Image.Image:
    im = Image.new('RGBA', (TILE, TILE), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # Rails meet at the cell's center and continue only toward connected fence tiles.
    horizontal = bool(mask & (2 | 8))
    vertical = bool(mask & (1 | 4))
    if not (horizontal or vertical):
        horizontal = True
    if horizontal:
        left, right = (0, 31) if mask & 8 else (15, 31) if mask & 2 else (15, 16)
        if mask & 2 and mask & 8: left, right = 0, 31
        d.rectangle((left, 13, right, 15), fill=PAL['wood_dark'])
        d.rectangle((left, 21, right, 23), fill=PAL['wood_dark'])
        d.rectangle((left, 12, right, 13), fill=PAL['wood_lit'])
        d.rectangle((left, 20, right, 21), fill=PAL['wood_lit'])
    if vertical:
        top, bottom = (0, 31) if mask & 1 else (15, 31) if mask & 4 else (15, 16)
        if mask & 1 and mask & 4: top, bottom = 0, 31
        d.rectangle((12, top, 14, bottom), fill=PAL['wood_dark'])
        d.rectangle((21, top, 23, bottom), fill=PAL['wood_dark'])
        d.rectangle((11, top, 12, bottom), fill=PAL['wood_lit'])
        d.rectangle((20, top, 21, bottom), fill=PAL['wood_lit'])
    d.rectangle((11, 10, 16, 26), fill=PAL['wood_dark'])
    d.rectangle((12, 10, 15, 24), fill=PAL['wood_lit'])
    d.rectangle((19, 10, 24, 26), fill=PAL['wood_dark'])
    d.rectangle((20, 10, 23, 24), fill=PAL['wood_lit'])
    d.rectangle((11, 25, 24, 27), fill=PAL['shadow'])
    return im


def detail_cell(index: int) -> Image.Image:
    im = Image.new('RGBA', (TILE, TILE), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if index < 4:  # wildflower clumps
        colors = [PAL['flower_yellow'], PAL['flower_white'], PAL['flower_pink'], PAL['flower_yellow']]
        for x, y in ((8, 15), (15, 10), (21, 19), (12, 23), (25, 11)):
            d.rectangle((x, y + 3, x + 1, y + 7), fill=PAL['grass_deep'])
            d.rectangle((x - 1, y - 1, x + 2, y + 1), fill=colors[(x + y + index) % len(colors)])
            px(d, x, y, PAL['cream'])
    elif index in (4, 5):  # stone clusters
        d.ellipse((5, 16, 13, 23), fill=PAL['shadow'])
        d.ellipse((6, 13, 14, 20), fill=PAL['stone'])
        d.ellipse((18, 18, 27, 25), fill=PAL['shadow'])
        d.ellipse((18, 15, 26, 22), fill='#aaa58d')
        px(d, 8, 15, '#c5bda1')
    elif index in (6, 7):  # tufts and clover
        for x, y in ((7, 20), (15, 13), (24, 21)):
            d.polygon([(x, y + 7), (x + 3, y), (x + 4, y + 7)], fill=PAL['grass_lit'])
            px(d, x + 4, y + 2, PAL['grass_dark'])
    elif index in (8, 9):  # hay bale
        d.rectangle((5, 12, 26, 25), fill='#b38b4e')
        d.rectangle((7, 10, 24, 23), fill='#d0a859')
        for y in (13, 18): d.line((9, y, 22, y - 1), fill='#e0c477', width=1)
        d.rectangle((13, 10, 15, 23), fill='#987644')
    elif index in (10, 11):  # crate / barrel
        d.rectangle((7, 12, 24, 26), fill=PAL['wood_dark'])
        d.rectangle((8, 11, 23, 24), fill=PAL['wood_lit'])
        d.rectangle((10, 13, 12, 22), fill=PAL['wood_dark'])
        d.rectangle((19, 13, 21, 22), fill=PAL['wood_dark'])
        d.line((8, 17, 23, 17), fill='#c59662')
    elif index in (12, 13):  # water trough
        d.rectangle((4, 12, 27, 25), fill=PAL['wood_dark'])
        d.rectangle((6, 11, 25, 22), fill=PAL['water_deep'])
        d.rectangle((8, 12, 23, 19), fill=PAL['water'])
        d.line((8, 13, 15, 13), fill=PAL['water_lit'], width=1)
        d.rectangle((7, 24, 10, 27), fill=PAL['wood_lit'])
        d.rectangle((21, 24, 24, 27), fill=PAL['wood_lit'])
    elif index == 14:  # hand-painted direction sign
        d.rectangle((15, 15, 17, 28), fill=PAL['wood_dark'])
        d.rectangle((5, 7, 27, 17), fill='#ead7a5', outline=PAL['wood_dark'])
        d.line((8, 10, 20, 10), fill=PAL['wood_lit'])
        d.line((8, 13, 16, 13), fill=PAL['wood_lit'])
    elif index == 15:  # small receiver post, intentionally quiet
        d.rectangle((15, 13, 17, 27), fill=PAL['wood_dark'])
        d.rectangle((10, 25, 22, 28), fill=PAL['wood_lit'])
        d.ellipse((11, 7, 21, 17), fill='#6d8d86', outline=PAL['wood_dark'])
        d.ellipse((14, 10, 18, 14), fill=PAL['water_lit'])
    return im


def tile_atlas() -> Image.Image:
    atlas = Image.new('RGBA', (COLS * TILE, ROWS * TILE), (0, 0, 0, 0))
    tiles = ([grass_cell(i) for i in range(8)] + [path_cell(i) for i in range(16)]
             + [fence_cell(i) for i in range(16)] + [detail_cell(i) for i in range(16)])
    for index, tile in enumerate(tiles):
        atlas.alpha_composite(tile, ((index % COLS) * TILE, (index // COLS) * TILE))
    return atlas


COATS = [('#f0eadb', '#292c2c'), ('#a7653c', '#3d3028'), ('#dfd5bc', '#756d5d'), ('#454847', '#ddd8c9')]
DIRECTIONS = ['north', 'east', 'south', 'west']
ACTIONS = ['idle', 'graze', 'walk', 'drink', 'turn']


def cow_frame(coat: int, direction: int, action: int, frame: int) -> Image.Image:
    im = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    base, patch = COATS[coat]
    d.ellipse((5, 8, 26, 26), fill=(42, 51, 39, 76))
    for leg in (8, 12, 20, 24):
        offset = frame if action == 2 and (leg + frame) % 2 == 0 else 0
        d.rectangle((leg, 23 - offset, leg + 2, 27 - offset), fill='#49443a')
    d.ellipse((6, 7, 25, 24), fill=base, outline='#49463e')
    if coat in (0, 3):
        d.polygon([(9, 10), (14, 9), (17, 13), (13, 17), (8, 15)], fill=patch)
        d.polygon([(19, 17), (24, 15), (24, 21), (19, 23), (16, 20)], fill=patch)
    elif coat == 1:
        d.polygon([(8, 11), (12, 9), (15, 12), (12, 16), (8, 15)], fill=patch)
    else:
        d.polygon([(18, 10), (22, 12), (21, 16), (17, 15)], fill=patch)
    hx, hy = [(15, 7), (25, 14), (15, 23), (6, 14)][direction]
    d.ellipse((hx - 4, hy - 3, hx + 4, hy + 4), fill=base, outline='#49463e')
    d.rectangle((hx - 1, hy + 1, hx + 2, hy + 3), fill='#bd8270')
    d.rectangle((hx + (2 if direction % 2 else 4), hy - 2, hx + (4 if direction % 2 else 5), hy), fill=PAL['tag'])
    if action == 1: d.line((hx, hy + 1, hx, hy + 5), fill=base, width=2)
    if action == 3: d.line((hx, hy + 1, hx + 3, hy + 3), fill=base, width=2)
    return im


def cattle_atlas() -> Image.Image:
    im = Image.new('RGBA', (16 * 32, 10 * 32), (0, 0, 0, 0))
    for coat in range(4):
        for direction in range(4):
            for action in range(5):
                for frame in range(2):
                    index = (((coat * 4 + direction) * 5 + action) * 2 + frame)
                    im.alpha_composite(cow_frame(coat, direction, action, frame),
                                       ((index % 16) * 32, (index // 16) * 32))
    return im


def tree_atlas() -> Image.Image:
    im = Image.new('RGBA', (5 * 64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    variants = [('#426848', '#688a52'), ('#456c53', '#82965c'), ('#536c47', '#a0834e'),
                ('#345b4b', '#638d69'), ('#5b7048', '#8a9e5e')]
    for i, (deep, light) in enumerate(variants):
        x = i * 64
        d.ellipse((x + 5, 45, x + 58, 60), fill=(42, 53, 38, 90))
        d.rectangle((x + 28, 39, x + 36, 57), fill='#71513a')
        for bx, by, rx, ry in ((17, 29, 14, 14), (31, 20, 17, 17), (45, 31, 13, 14), (29, 38, 17, 12)):
            d.ellipse((x + bx - rx, by - ry, x + bx + rx, by + ry), fill=deep, outline='#344d3d')
        for bx, by, rx, ry in ((25, 17, 9, 8), (38, 25, 8, 7), (17, 31, 7, 6)):
            d.ellipse((x + bx - rx, by - ry, x + bx + rx, by + ry), fill=light)
        for dx, dy in ((14, 21), (33, 11), (44, 33), (26, 37)):
            px(d, x + dx, dy, '#a4ae69' if i == 2 else '#8ea46a')
    return im


def barn_image() -> Image.Image:
    im = Image.new('RGBA', (192, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((12, 112, 182, 153), fill=(40, 48, 35, 92))
    # Raised cream timber base and broad, warm-red roof.
    d.polygon([(20, 52), (95, 14), (173, 52), (173, 118), (96, 147), (20, 116)], fill='#79553c')
    d.polygon([(18, 46), (94, 8), (176, 47), (175, 106), (96, 137), (19, 105)], fill='#8d4538', outline='#56382f')
    d.polygon([(23, 47), (95, 12), (95, 131), (23, 103)], fill='#a95643')
    d.polygon([(99, 13), (171, 48), (169, 103), (99, 131)], fill='#77443a')
    for n in range(8):
        x = 31 + n * 8
        y = 43 - n * 4
        d.line((x, y, x, y + 58 + n * 2), fill='#c17a58' if n % 2 else '#9a5544', width=2)
    # Front gable, dark doorway and loft window.
    d.polygon([(64, 101), (96, 82), (128, 101), (128, 137), (64, 137)], fill='#c99a65', outline='#674735')
    d.polygon([(64, 101), (96, 82), (96, 137), (64, 137)], fill='#dfb77b')
    d.rectangle((84, 111, 107, 137), fill='#49372e')
    d.rectangle((87, 114, 104, 137), fill='#604538')
    d.rectangle((88, 91, 104, 103), fill='#44584c', outline='#674735')
    d.line((96, 91, 96, 103), fill='#dfc38c', width=2)
    d.line((88, 97, 104, 97), fill='#dfc38c', width=2)
    d.rectangle((76, 136, 116, 141), fill='#5b4034')
    # Vent and chimney to anchor the roof silhouette.
    d.rectangle((139, 24, 151, 48), fill='#5c4034', outline='#392f29')
    d.rectangle((136, 21, 154, 26), fill='#44352e')
    d.rectangle((47, 65, 55, 83), fill='#754438')
    d.rectangle((45, 62, 57, 66), fill='#49372f')
    return im


def shed_image() -> Image.Image:
    im = Image.new('RGBA', (96, 88), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((5, 65, 92, 84), fill=(40, 48, 35, 86))
    d.polygon([(10, 29), (47, 8), (87, 28), (87, 66), (48, 79), (10, 65)], fill='#77533b')
    d.polygon([(9, 25), (47, 5), (89, 25), (87, 58), (48, 72), (10, 58)], fill='#758b5a', outline='#4a5941')
    d.polygon([(13, 26), (47, 9), (47, 68), (13, 57)], fill='#8fa665')
    d.polygon([(51, 10), (85, 27), (84, 57), (51, 68)], fill='#657d50')
    d.rectangle((37, 42, 57, 69), fill='#514136')
    d.rectangle((39, 44, 55, 68), fill='#9b714a')
    d.line((14, 32, 47, 17), fill='#b2be78', width=2)
    return im


def pond_image() -> Image.Image:
    im = Image.new('RGBA', (224, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((8, 33, 214, 151), fill=(48, 62, 41, 95))
    d.ellipse((7, 23, 215, 146), fill='#967e54')
    d.ellipse((14, 19, 210, 138), fill='#d0b17a')
    d.ellipse((20, 14, 203, 131), fill='#397d72')
    d.ellipse((28, 17, 193, 123), fill='#518f85')
    d.arc((30, 18, 198, 124), 195, 340, fill='#96b78c', width=3)
    # Reeds and water lilies make the pond legible at overview scale.
    for x, y in ((28, 51), (39, 45), (187, 76), (174, 109), (59, 118), (198, 46)):
        d.line((x, y + 12, x + 1, y - 2), fill='#536f46', width=2)
        d.polygon([(x, y + 3), (x - 6, y - 5), (x - 2, y + 4)], fill='#7b9657')
    for x, y in ((77, 59), (131, 41), (153, 92), (103, 103)):
        d.ellipse((x - 5, y - 2, x + 6, y + 2), fill='#91b77f')
        px(d, x + 1, y, '#e0cb88')
    return im


def point(tile_x: float, tile_y: float) -> tuple[float, float]:
    return ((tile_x + 0.5) * TILE, (tile_y + 0.5) * TILE)


def line_cells(points: list[tuple[int, int]]) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        sx, sy = (1 if x1 < x2 else -1), (1 if y1 < y2 else -1)
        error = dx - dy
        x, y = x1, y1
        while True:
            cells.add((x, y))
            if x == x2 and y == y2: break
            twice = error * 2
            if twice > -dy: error -= dy; x += sx
            if twice < dx: error += dx; y += sy
    return cells


def polygon_fence(vertices: list[tuple[int, int]]) -> set[tuple[int, int]]:
    return line_cells(vertices + [vertices[0]])


def neighbor_mask(cells: set[tuple[int, int]], x: int, y: int) -> int:
    # Diagonal steps from the hand-drawn boundary still join a rail on its
    # dominant axis, avoiding a row of disconnected default-facing posts.
    north = (x, y - 1) in cells or (x - 1, y - 1) in cells or (x + 1, y - 1) in cells
    east = (x + 1, y) in cells or (x + 1, y - 1) in cells or (x + 1, y + 1) in cells
    south = (x, y + 1) in cells or (x - 1, y + 1) in cells or (x + 1, y + 1) in cells
    west = (x - 1, y) in cells or (x - 1, y - 1) in cells or (x - 1, y + 1) in cells
    return (1 if north else 0) | (2 if east else 0) | (4 if south else 0) | (8 if west else 0)


def make_map() -> dict:
    ground = [0] * (W * H)
    paths = [0] * (W * H)
    fences = [0] * (W * H)
    details = [0] * (W * H)

    def put(layer: list[int], x: int, y: int, gid: int) -> None:
        if 0 <= x < W and 0 <= y < H: layer[y * W + x] = gid

    # Subtle tile-to-tile variations preserve a continuous meadow rather than a checkerboard.
    for y in range(H):
        for x in range(W):
            variant = (x * 13 + y * 7 + x * y * 3) % 8
            put(ground, x, y, variant + 1)

    # A meandering footpath follows the barn, pond and pasture gates.
    routes = [
        [(1, 42), (5, 40), (9, 37), (14, 36), (18, 33), (21, 29), (25, 27),
         (28, 23), (33, 22), (38, 24), (42, 22), (46, 18), (52, 17), (58, 13), (63, 11)],
        [(21, 29), (19, 25), (17, 22), (17, 18), (15, 15), (14, 11), (12, 8)],
        [(38, 24), (42, 27), (47, 28), (52, 31), (56, 35)],
        [(25, 27), (25, 31), (27, 35), (29, 40)],
        [(46, 18), (43, 15), (42, 12), (39, 10)],
    ]
    path_cells: set[tuple[int, int]] = set()
    for route_index, route in enumerate(routes):
        centerline = line_cells(route)
        for x, y in centerline:
            radius = 1 if (x + y + route_index) % 5 else 2
            for oy in range(-radius, radius + 1):
                for ox in range(-radius, radius + 1):
                    if ox * ox + oy * oy <= radius * radius + 1:
                        if 0 <= x + ox < W and 0 <= y + oy < H:
                            path_cells.add((x + ox, y + oy))
    for x, y in path_cells:
        put(paths, x, y, 9 + neighbor_mask(path_cells, x, y))  # atlas index 8 + mask

    pasture_vertices = [
        [(4, 17), (5, 13), (10, 11), (16, 12), (20, 17), (21, 23), (17, 28), (10, 29), (5, 25)],
        [(30, 10), (38, 7), (47, 9), (54, 13), (57, 18), (53, 23), (47, 25), (39, 24), (33, 20), (29, 15)],
        [(19, 31), (24, 28), (30, 29), (35, 32), (37, 37), (32, 41), (25, 40), (20, 36)],
        [(42, 28), (47, 26), (53, 28), (57, 32), (55, 37), (49, 39), (43, 36), (40, 32)],
    ]
    fence_cells: set[tuple[int, int]] = set()
    for vertices in pasture_vertices:
        fence_cells.update(polygon_fence(vertices))
    # Gate gaps face the paths instead of repeating in the middle of every boundary.
    for gate in ((5, 21), (30, 15), (24, 36), (42, 32)):
        fence_cells.discard(gate)
        fence_cells.discard((gate[0], gate[1] - 1))
        fence_cells.discard((gate[0], gate[1] + 1))
    for x, y in fence_cells:
        put(fences, x, y, 25 + neighbor_mask(fence_cells, x, y))  # atlas index 24 + mask

    # Scattered hand-authored clumps, not a uniform blanket of decorative dots.
    flower_clusters = [(8, 17), (11, 20), (16, 24), (34, 13), (40, 17), (49, 14),
                       (26, 34), (31, 37), (47, 33), (53, 35), (7, 31), (15, 34),
                       (21, 8), (25, 11), (57, 24), (37, 29), (4, 39), (60, 37)]
    for i, (x, y) in enumerate(flower_clusters):
        put(details, x, y, 41 + i % 4)  # atlas indices 40-43
    for i, (x, y) in enumerate([(23, 13), (27, 15), (36, 27), (39, 35), (18, 39), (58, 7)]):
        put(details, x, y, 45 + i % 2)  # stones
    for i, (x, y) in enumerate([(9, 25), (19, 9), (36, 8), (55, 21), (33, 39)]):
        put(details, x, y, 49 + i % 2)  # hay
    for x, y, atlas_index in [(24, 25, 52), (38, 26, 53), (48, 27, 56),
                              (34, 24, 50), (16, 30, 54), (58, 28, 55)]:
        put(details, x, y, atlas_index + 1)

    layers = []
    for layer_id, name, data in [(1, 'ground', ground), (2, 'paths', paths),
                                 (3, 'fences', fences), (4, 'details', details)]:
        layers.append({'id': layer_id, 'name': name, 'type': 'tilelayer', 'x': 0, 'y': 0,
                       'width': W, 'height': H, 'opacity': 1, 'visible': True, 'data': data})

    tree_points = [(3, 4, 0), (7, 3, 1), (11, 5, 3), (18, 4, 2), (24, 5, 1),
                   (28, 3, 4), (34, 3, 0), (45, 4, 2), (52, 5, 1), (60, 4, 3),
                   (3, 10, 2), (7, 8, 4), (20, 7, 0), (26, 9, 2), (59, 10, 1),
                   (3, 29, 3), (7, 34, 0), (13, 38, 2), (17, 41, 1), (36, 42, 3),
                   (39, 39, 4), (60, 25, 2), (61, 38, 0), (6, 42, 1), (57, 41, 3)]
    landmark_objects = []
    next_object_id = 1
    for tx, ty, variant in tree_points:
        landmark_objects.append({'id': next_object_id, 'name': 'Canopy', 'type': 'tree',
                                 'x': (tx + 0.5) * TILE, 'y': (ty + 0.9) * TILE,
                                 'width': 64, 'height': 64, 'point': True,
                                 'properties': [{'name': 'variant', 'type': 'int', 'value': variant}]})
        next_object_id += 1
    landmark_objects.extend([
        {'id': next_object_id, 'name': 'Millpond', 'type': 'pond', 'x': 12 * TILE,
         'y': 8 * TILE, 'width': 224, 'height': 160, 'point': True},
        {'id': next_object_id + 1, 'name': 'Red barn', 'type': 'barn', 'x': 26.5 * TILE,
         'y': 18.5 * TILE, 'width': 192, 'height': 160, 'point': True},
        {'id': next_object_id + 2, 'name': 'Field shed', 'type': 'shed', 'x': 50 * TILE,
         'y': 34 * TILE, 'width': 96, 'height': 88, 'point': True},
    ])
    layers.append({'id': 5, 'name': 'landmarks', 'type': 'objectgroup', 'draworder': 'topdown',
                   'objects': landmark_objects, 'opacity': 1, 'visible': True})
    anchor_points = [(17, 8), (51, 10), (15, 36), (49, 36)]
    layers.append({'id': 6, 'name': 'anchors', 'type': 'objectgroup', 'draworder': 'topdown',
                   'objects': [{'id': i + 1, 'name': f'Receiver {i + 1}', 'type': 'receiver-anchor',
                                'x': (x + .5) * TILE, 'y': (y + .5) * TILE, 'width': 0, 'height': 0,
                                'point': True, 'properties': [{'name': 'anchorIndex', 'type': 'int', 'value': i}]}
                               for i, (x, y) in enumerate(anchor_points)],
                   'opacity': 1, 'visible': True})
    return {'compressionlevel': -1, 'height': H, 'infinite': False, 'layers': layers,
            'nextlayerid': 7, 'nextobjectid': next_object_id + 3, 'orientation': 'orthogonal',
            'renderorder': 'right-down', 'tiledversion': '1.10.2', 'tileheight': TILE,
            'tilesets': [{'columns': COLS, 'firstgid': 1, 'image': 'farm-tiles.png',
                          'imageheight': ROWS * TILE, 'imagewidth': COLS * TILE, 'margin': 0,
                          'name': 'riose-farm-tiles', 'spacing': 0, 'tilecount': COLS * ROWS,
                          'tileheight': TILE, 'tilewidth': TILE}],
            'tilewidth': TILE, 'type': 'map', 'version': '1.10', 'width': W}


if __name__ == '__main__':
    ROOT.mkdir(parents=True, exist_ok=True)
    tile_atlas().save(ROOT / 'farm-tiles.png', optimize=True)
    cattle_atlas().save(ROOT / 'cattle-atlas.png', optimize=True)
    diorama = Image.open(SOURCE_ART).convert('RGB').resize((512, 352), Image.Resampling.LANCZOS)
    diorama = diorama.quantize(colors=64, method=Image.Quantize.MEDIANCUT,
                               dither=Image.Dither.NONE).convert('RGB')
    diorama.resize((W * TILE, H * TILE), Image.Resampling.NEAREST).save(
        ROOT / 'diorama.png', optimize=True)
    (ROOT / 'farm-map.json').write_text(json.dumps(make_map(), indent=2) + '\n')
    print(f'Generated {ROOT}: {W}x{H} Tiled map, cattle atlas and pixelated diorama')
