"""Clean the generated logo: transparent background, square crop, and lemon + golden variants.
Usage: python yuja/logo/clean.py   (reads source.png, writes logo_lemon.png / logo_golden.png next to it)"""
from collections import deque
from pathlib import Path
from PIL import Image

HERE = Path(__file__).parent
GOLDEN = (255, 194, 26)          # Yuja's --y-new token
WARM = (255, 220, 10)            # between the drawing's lemon yellow and GOLDEN
LEAF, GRASS = (100, 231, 87), (92, 201, 59)   # the drawing's leaf green -> warmer grass green

def transparent(im):
    """Flood the near-white background from the edges; anti-aliased outline pixels become black with partial alpha."""
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    light = lambda p: min(p[:3]) > 200
    seen, q = set(), deque((x, y) for x in range(w) for y in (0, h - 1)) + deque((x, y) for y in range(h) for x in (0, w - 1))
    while q:
        x, y = q.popleft()
        if (x, y) in seen or not (0 <= x < w and 0 <= y < h):
            continue
        seen.add((x, y))
        r, g, b, a = px[x, y]
        if light(px[x, y]):
            px[x, y] = (0, 0, 0, 0)
            q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
        elif max(r, g, b) - min(r, g, b) < 40:            # gray edge between outline and background
            px[x, y] = (0, 0, 0, 255 - min(r, g, b))
    return im

def square(im, fill=0.92):
    """Crop to the drawing and center it in a square so it fills ~92% of the side."""
    im = im.crop(im.getbbox())
    side = round(max(im.size) / fill)
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return out

def recolor(im, target):
    """Swap the yellow (and its blends with the black outline) for target; green and black stay."""
    im = im.copy()
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if a and b < 80 and r > 30 and r >= 0.85 * g:   # yellow-ish (green has r well below g)
                k = (r + g) / (255 + 239)
                px[x, y] = (*(round(k * c) for c in target), a)
    return im

def bumpy(im, amp=0.010, seed=3):
    """Lumpy yuja peel: push the fruit's edge (fill + outline together) in and out around the circle.
    The top arc, where the stem and leaf sit, stays as drawn; the face is well inside and untouched."""
    import math, random
    im = im.copy()
    px, w = im.load(), im.width
    yellow = lambda p: p[3] > 200 and p[2] < 80 and p[0] > 200 and p[1] > 150
    pts = [(x, y) for y in range(w) for x in range(w) if yellow(px[x, y])]
    cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    N = 720
    ang = lambda x, y: (math.degrees(math.atan2(x - cx, cy - y)) % 360)          # 0 = up, clockwise
    inner, outer = [0.0] * N, [0.0] * N                 # fill radius and outline radius per angle
    for y in range(w):
        for x in range(w):
            p = px[x, y]
            if p[3] < 128 or (p[1] > p[0] + 40):        # transparent or leaf/stem green
                continue
            i, r = int(ang(x, y) * N / 360) % N, math.hypot(x - cx, y - cy)
            outer[i] = max(outer[i], r)
            if yellow(p):
                inner[i] = max(inner[i], r)
    med = lambda a, i: sorted(a[(i + k) % N] for k in range(-4, 5))[4]       # smooth out ragged bins
    inner, outer = [med(inner, i) for i in range(N)], [med(outer, i) for i in range(N)]
    rnd = random.Random(seed)
    lumps = [(k, rnd.uniform(0, 2 * math.pi), wgt) for k, wgt in ((9, .5), (13, .3), (21, .2))]
    def bump(deg):
        if deg < 55 or deg > 320:                       # protected arc: stem + leaf (top to upper right)
            return 0.0
        fade = min(1.0, (deg - 55) / 25, (320 - deg) / 25)
        t = math.radians(deg)
        return fade * amp * w * sum(wgt * math.sin(k * t + ph) for k, ph, wgt in lumps)
    for y in range(w):
        for x in range(w):
            deg = ang(x, y)
            b = bump(deg)
            if not b:
                continue
            i, r = int(deg * N / 360) % N, math.hypot(x - cx, y - cy)
            R, O = inner[i], outer[i]
            if r < R + b and r > R - abs(b) - 2:
                px[x, y] = (255, 239, 2, 255)
            elif R + b <= r < O + b and r > R - abs(b) - 2:
                px[x, y] = (0, 0, 0, 255)
            elif r >= O + b and r < O + abs(b) + 4:
                px[x, y] = (0, 0, 0, 0)
    return im

base = square(transparent(Image.open(HERE / "source.png")))
def releaf(im, target):
    """Swap the leaf/stem green (and its blends with the outline) for target."""
    im = im.copy()
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if a and g > r + 40:
                px[x, y] = (*(min(255, round(g / LEAF[1] * c)) for c in target), a)
    return im

releaf(recolor(bumpy(base), WARM), GRASS).save(HERE / "logo_warm.png")
base.save(HERE / "logo_lemon.png")
recolor(base, GOLDEN).save(HERE / "logo_golden.png")
print(base.size)
