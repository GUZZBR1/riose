#!/usr/bin/env python3
"""Reproducibly generate the hand-composed RIOSE pixel farm atlases and Tiled map."""
from __future__ import annotations
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = (Path(__file__).resolve().parents[2]
        / 'src/riose/products/livestock_tracking/adapters/static/assets/farm-demo')
TILE = 32
COLS, ROWS = 8, 4
PAL = {
    'grass': '#879a70', 'grass_light': '#9cab7d', 'grass_dark': '#71865f',
    'cream': '#e5dfc9', 'dirt': '#b49a78', 'dirt_light': '#c9b08a', 'dirt_dark': '#9a8062',
    'wood': '#735a48', 'wood_light': '#9c795b', 'roof': '#66594f', 'roof_light': '#827367',
    'water': '#718f91', 'water_light': '#a7c0b4', 'leaf': '#526b51', 'leaf_light': '#748666',
    'black': '#303331', 'white': '#eee9dc', 'tag': '#d1ae43', 'metal': '#66716d',
}

def rect(d, box, color): d.rectangle(box, fill=color)
def pixel(d, xy, color): d.rectangle((xy[0], xy[1], xy[0]+1, xy[1]+1), fill=color)

def tile_image():
    im = Image.new('RGBA', (COLS*TILE, ROWS*TILE), (0,0,0,0)); d=ImageDraw.Draw(im)
    # IDs 0-7: terrain and paths; deterministic flecks make the field feel authored.
    for i in range(8):
        x=(i%COLS)*TILE; y=(i//COLS)*TILE
        if i in (0,1,2,3):
            # Keep the field tone continuous across cells; only tiny pixel flecks
            # vary so the tile grid doesn't read as a checkerboard at overview zoom.
            base=PAL['grass']
            rect(d,(x,y,x+31,y+31),base)
            marks = [[(4,7, PAL['grass_light']), (22,22,PAL['grass_dark'])],
                     [(7,21,PAL['grass_light']), (24,6,PAL['grass_dark'])],
                     [(5,5,PAL['grass_light']), (19,24,PAL['grass_dark'])],
                     [(12,13,PAL['grass_dark']), (27,19,PAL['grass_light'])]][i]
            for px,py,c in marks: pixel(d,(x+px,y+py),c)
            if i==1:
                pixel(d,(x+15,y+8),PAL['cream']); pixel(d,(x+16,y+8),PAL['tag'])
        elif i in (4,5,6):
            rect(d,(x,y,x+31,y+31),PAL['dirt'])
            for px,py,c in [(3,7,PAL['dirt_light']),(17,25,PAL['dirt_dark']),(26,12,PAL['dirt_light'])]: pixel(d,(x+px,y+py),c)
            if i==5: rect(d,(x,y+2,x+31,y+29),PAL['dirt_light'])
            if i==6: rect(d,(x+2,y,x+29,y+31),PAL['dirt_light'])
        elif i==7:
            rect(d,(x,y,x+31,y+31),PAL['water'])
            for px,py in [(4,9),(16,17),(24,6),(10,25)]: rect(d,(x+px,y+py,x+px+4,y+py+1),PAL['water_light'])
    # 8-15: structure pieces. Tiles 8-11 are fence orientation/ends; 12-14 tree; 15 shrub.
    for i in range(8,16):
        x=(i%COLS)*TILE; y=(i//COLS)*TILE
        if i==8: # horizontal fence
            rect(d,(x,y+12,x+31,y+14),PAL['wood_light']); rect(d,(x,y+21,x+31,y+23),PAL['wood'])
            for px in (3,15,27): rect(d,(x+px,y+8,x+px+2,y+27),PAL['wood'])
        elif i==9: # vertical fence
            rect(d,(x+12,y,x+14,y+31),PAL['wood_light']); rect(d,(x+21,y,x+23,y+31),PAL['wood'])
            for py in (3,15,27): rect(d,(x+8,y+py,x+27,y+py+2),PAL['wood'])
        elif i==10: # fence corner
            rect(d,(x,y+12,x+31,y+14),PAL['wood_light']); rect(d,(x,y+21,x+31,y+23),PAL['wood'])
            rect(d,(x+17,y,x+19,y+31),PAL['wood_light']); rect(d,(x+24,y,x+26,y+31),PAL['wood'])
            for px,py in ((2,8),(16,7),(27,19)): rect(d,(x+px,y+py,x+px+2,y+py+9),PAL['wood'])
        elif i==11: # gate opening / post pair
            rect(d,(x+3,y+9,x+5,y+26),PAL['wood']); rect(d,(x+26,y+9,x+28,y+26),PAL['wood'])
            rect(d,(x+7,y+12,x+15,y+14),PAL['wood_light']); rect(d,(x+16,y+21,x+24,y+23),PAL['wood'])
        elif i in (12,13,14):
            # canopy clusters differ in shape; shadow is part of sprite.
            rect(d,(x+5,y+24,x+26,y+29), '#637454')
            if i==12: d.ellipse((x+5,y+3,x+26,y+25),fill=PAL['leaf'],outline='#435843'); d.ellipse((x+9,y+2,x+20,y+15),fill=PAL['leaf_light'])
            elif i==13: d.ellipse((x+2,y+8,x+28,y+27),fill='#5c7355',outline='#435843'); d.ellipse((x+7,y+3,x+22,y+20),fill=PAL['leaf_light'])
            else: d.ellipse((x+7,y+4,x+24,y+27),fill='#687d5d',outline='#435843'); d.ellipse((x+10,y+5,x+18,y+16),fill='#8b9870')
            rect(d,(x+14,y+21,x+17,y+27),PAL['wood'])
        elif i==15:
            d.ellipse((x+5,y+12,x+26,y+27),fill=PAL['leaf'],outline='#435843'); pixel(d,(x+12,y+14),PAL['leaf_light'])
    # 16-23: barn, trough, receiver, details.
    for i in range(16,24):
        x=(i%COLS)*TILE; y=(i//COLS)*TILE
        if i==16: # modular top-down barn roof tile
            rect(d,(x+1,y+4,x+30,y+19),PAL['roof'])
            rect(d,(x+1,y+4,x+30,y+6),PAL['black'])
            for yy in (9,14): rect(d,(x+2,y+yy,x+29,y+yy+1),PAL['roof_light'])
            rect(d,(x+1,y+18,x+30,y+20),PAL['wood'])
        elif i==17: # barn facade
            rect(d,(x+6,y+11,x+26,y+29),PAL['wood_light']); rect(d,(x+9,y+14,x+23,y+29),PAL['wood'])
            rect(d,(x+12,y+19,x+20,y+29),PAL['black']); rect(d,(x+13,y+21,x+19,y+29),PAL['wood_light'])
            rect(d,(x+3,y+28,x+29,y+30),PAL['dirt_dark'])
        elif i==18: # barn side
            rect(d,(x+4,y+8,x+27,y+29),PAL['wood_light']); rect(d,(x+4,y+8,x+27,y+11),PAL['roof'])
            rect(d,(x+8,y+15,x+12,y+20),PAL['cream']); rect(d,(x+19,y+15,x+23,y+20),PAL['cream'])
            rect(d,(x+4,y+27,x+27,y+29),PAL['wood'])
        elif i==19: # water trough
            rect(d,(x+4,y+10,x+27,y+25),PAL['metal']); rect(d,(x+6,y+12,x+25,y+22),PAL['water'])
            rect(d,(x+7,y+14,x+13,y+15),PAL['water_light']); rect(d,(x+8,y+25,x+10,y+28),PAL['wood'])
            rect(d,(x+21,y+25,x+23,y+28),PAL['wood'])
        elif i==20: # receiver anchor, subtle mast + yellow head
            rect(d,(x+15,y+12,x+17,y+28),PAL['metal']); rect(d,(x+11,y+26,x+21,y+28),PAL['wood'])
            d.ellipse((x+11,y+5,x+21,y+15),fill=PAL['tag'],outline=PAL['wood']); pixel(d,(x+15,y+8),PAL['white'])
        elif i==21: # hay stack
            rect(d,(x+7,y+11,x+24,y+25), '#b59b61'); rect(d,(x+9,y+13,x+22,y+23),'#c9ad70')
            rect(d,(x+10,y+17,x+21,y+18),'#aa8f58')
        elif i==22: # water pump/utility box
            rect(d,(x+10,y+12,x+22,y+26),PAL['metal']); rect(d,(x+12,y+9,x+20,y+13),PAL['wood'])
            pixel(d,(x+16,y+17),PAL['tag'])
        else: # blank transparent utility tile
            pass
    return im

# Cow atlas organization: frame index = (((coat * 4 + direction) * 5 + action) * 2 + frame)
# coat: 0 black/white, 1 red, 2 cream, 3 dark; direction: north/east/south/west;
# action: idle/graze/walk/drink/turn. 160 32x32 frames in 16 columns x 10 rows.
COATS = [('#f0eadb','#292c2c'),('#a7653c','#3d3028'),('#dfd5bc','#756d5d'),('#454847','#ddd8c9')]
DIRECTIONS=['north','east','south','west']; ACTIONS=['idle','graze','walk','drink','turn']

def cow_frame(coat, direction, action, frame):
    im=Image.new('RGBA',(32,32),(0,0,0,0)); d=ImageDraw.Draw(im)
    base,patch=COATS[coat]
    # compact shadow, body and head are drawn as hard pixel clusters for crisp nearest-neighbor scaling.
    d.ellipse((5,8,26,26),fill=(35,42,37,70))
    # frame offsets provide restrained two-frame life without changing footprint
    step=1 if frame else 0
    legs_y=24
    for lx in (8,12,20,24):
        off=step if action=='walk' and ((lx+frame)%2==0) else 0
        d.rectangle((lx,legs_y-off,lx+2,27-off),fill='#49443a')
    d.ellipse((6,7,25,24),fill=base,outline='#49463e')
    if coat in (0,3):
        d.polygon([(9,10),(14,9),(17,13),(13,17),(8,15)],fill=patch)
        d.polygon([(19,17),(24,15),(24,21),(19,23),(16,20)],fill=patch)
    elif coat==1:
        d.polygon([(8,11),(12,9),(15,12),(12,16),(8,15)],fill=patch)
    else:
        d.polygon([(18,10),(22,12),(21,16),(17,15)],fill=patch)
    # Directions map to a head point; yellow ear tag is deliberately tiny but visible.
    points={'south':((15,23),(17,22),(20,21)), 'north':((15,7),(17,8),(12,8)), 'east':((25,14),(23,16),(24,11)), 'west':((6,14),(8,16),(7,11))}
    hx,hy=points[DIRECTIONS[direction]][0]
    if direction in (0,2):
        d.ellipse((11,hy-3,20,hy+3),fill=base,outline='#49463e')
        if direction==2: d.rectangle((13,hy+1,18,hy+3),fill='#bd8270')
        else: d.rectangle((13,hy-3,18,hy-1),fill=patch)
    elif direction==1:
        d.ellipse((hx-3,hy-4,hx+3,hy+4),fill=base,outline='#49463e'); d.rectangle((hx+1,hy-1,hx+3,hy+1),fill='#bd8270')
    else:
        d.ellipse((hx-3,hy-4,hx+3,hy+4),fill=base,outline='#49463e'); d.rectangle((hx-3,hy-1,hx-1,hy+1),fill='#bd8270')
    tx,ty=points[DIRECTIONS[direction]][1]
    d.rectangle((tx,ty,tx+2,ty+2),fill=PAL['tag'],outline='#8e7336')
    # activity cue: grazing head dip, drinking toward a trough, and gentle turn ear/leg shift.
    if action==1: d.line((hx,hy+1,hx,hy+4),fill=base,width=2)
    elif action==3: d.line((hx,hy,hx+(2 if direction==1 else -2),hy+2),fill=base,width=2)
    elif action==4: pixel(d,(13+frame,8),PAL['tag'])
    return im

def cattle_image():
    im=Image.new('RGBA',(16*32,10*32),(0,0,0,0))
    for coat in range(4):
      for direction in range(4):
       for action in range(5):
        for frame in range(2):
         idx=(((coat*4+direction)*5+action)*2+frame)
         im.alpha_composite(cow_frame(coat,direction,action,frame),((idx%16)*32,(idx//16)*32))
    return im

W,H=48,32

def make_map():
    ground=[0]*(W*H); paths=[0]*(W*H); structures=[0]*(W*H)
    def setv(layer,x,y,gid):
        if 0<=x<W and 0<=y<H: layer[y*W+x]=gid
    # Softly varied hand-composed field, with deterministic scattered grass flecks.
    for y in range(H):
      for x in range(W):
       v=(x*17+y*31+x*y*3)%19
       setv(ground,x,y,2 if v in (0,1) else 3 if v==2 else 1 if v in (3,4,5) else 1)
    # Main loop/cross dirt roads and four access spurs, tile GIDs offset by one (Tiled indexing).
    for x in range(1,47):
      for dy in (-1,0,1): setv(paths,x,16+dy,4 if dy==0 else 5)
    for y in range(2,30):
      for dx in (-1,0,1): setv(paths,24+dx,y,4 if dx==0 else 6)
    for y0,y1 in ((4,12),(20,28)):
      for x0,x1 in ((4,19),(29,44)):
       # paddock inner paths near entrances, muted and simple
       for xx in range(x0+1,x1): setv(paths,xx,y0+1,4)
    # four paddock fences: perimeter segments and gate gap facing central road
    for x0,x1,y0,y1 in ((3,19,3,13),(28,44,3,13),(3,19,19,29),(28,44,19,29)):
      for x in range(x0+1,x1):
       setv(structures,x,y0,8); setv(structures,x,y1,8)
      for y in range(y0+1,y1):
       setv(structures,x0,y,9); setv(structures,x1,y,9)
      for x,y in ((x0,y0),(x1,y0),(x0,y1),(x1,y1)): setv(structures,x,y,10)
      # opening in inner-facing edge
      gy=(y0+y1)//2
      if y0<16:
       setv(structures,x1,gy,0); setv(structures,x1,gy+1,0)
      else:
       setv(structures,x0,gy,0); setv(structures,x0,gy+1,0)
    # Central barn: continuous roof, modular side wall, one centered entrance.
    for x in range(21,28):
      setv(structures,x,12,16)
      setv(structures,x,13,18)
      setv(structures,x,14,18)
    setv(structures,24,14,17)
    for x in range(22,27): setv(structures,x,15,4)
    # trees and scrub intentionally grouped around edges, not scattered randomly
    for x,y,gid in [(2,2,13),(8,2,14),(15,2,13),(26,2,14),(34,2,13),(45,2,14),
                    (2,8,14),(21,5,13),(27,7,14),(46,9,13),(2,22,13),(20,26,14),
                    (27,25,13),(46,24,14),(8,30,13),(16,30,14),(33,30,13),(44,30,14)]:
       setv(structures,x,y,gid)
    # troughs, hay/utility props and four coverage anchors
    for x,y,gid in [(10,8,20),(37,8,20),(10,24,20),(37,24,20),
                    (15,9,19),(33,9,19),(15,24,19),(33,24,19),
                    (16,9,21),(32,9,21),(16,24,21),(32,24,21),
                    (30,14,19),(18,17,22),(29,17,20)]: setv(structures,x,y,gid)
    # All layers in Tiled JSON; tile-layer GIDs are 1-based, 0 stays transparent/empty.
    def nonzero_ids(arr): return [int(v+1) if v else 0 for v in arr]
    layer=[]
    for n,arr in enumerate((nonzero_ids(ground),nonzero_ids(paths),nonzero_ids(structures)),1):
      layer.append({'id':n,'name':['ground','paths','structures'][n-1],'type':'tilelayer','x':0,'y':0,'width':W,'height':H,'opacity':1,'visible':True,'data':arr})
    layer.append({'id':4,'name':'anchors','type':'objectgroup','draworder':'topdown','objects':[
      {'id':i+1,'name':f'Anchor {i+1}','type':'receiver-anchor','x':(x+.5)*32,'y':(y+.5)*32,'width':0,'height':0,'point':True,'properties':[{'name':'anchorIndex','type':'int','value':i}]} for i,(x,y) in enumerate([(10,8),(37,8),(10,24),(37,24)])
    ],'opacity':1,'visible':True})
    return {'compressionlevel':-1,'height':H,'infinite':False,'layers':layer,'nextlayerid':5,'nextobjectid':5,
      'orientation':'orthogonal','renderorder':'right-down','tiledversion':'1.10.2','tileheight':32,'tilesets':[{'columns':COLS,'firstgid':1,'image':'farm-tiles.png','imageheight':ROWS*32,'imagewidth':COLS*32,'margin':0,'name':'riose-farm-tiles','spacing':0,'tilecount':COLS*ROWS,'tileheight':32,'tilewidth':32}], 'tilewidth':32,'type':'map','version':'1.10','width':W}

if __name__=='__main__':
    tile_image().save(ROOT/'farm-tiles.png', optimize=True)
    cattle_image().save(ROOT/'cattle-atlas.png', optimize=True)
    (ROOT/'farm-map.json').write_text(json.dumps(make_map(),indent=2)+'\n')
    print(f'Generated {ROOT}: map {W}x{H} tiles, farm atlas {COLS*32}x{ROWS*32}px, cattle atlas 512x320px')
