"""Toolbar icons: pixel art at 16 and 32 px (no outline, so the fruit gets the space), and the
drawing itself at 48 and 128 px. Usage: python yuja/logo/pixels.py  (writes icon{16,32,48,128}_warm.png)
Y fruit · S gold shade (keeps the edge on white toolbars) · H highlight · G leaf + stem · e face · b blush
Shapes and proportions come from the drawing itself (outline removed), so the icon matches the logo."""
from pathlib import Path
from PIL import Image

HERE = Path(__file__).parent
COLORS = {"Y": (255, 220, 10), "S": (232, 160, 0), "H": (255, 246, 170), "G": (92, 201, 59),
          "e": (40, 30, 20), "b": (255, 140, 130)}

import math
from collections import deque

STEM_X = 222          # in logo_warm.png, green left of this (and below the leaf) is the stem
GROW = 8              # px of the (~12-15 px) outline handed back to the shapes
STEM_EXTRA = {16: 1, 32: 2}   # extra stem pixels on top of the drawing's proportions

def shapes():
    """Label the drawing (logo_warm.png) with the outline removed: Y fruit, T stem, G leaf, F face, . nothing."""
    im = Image.open(HERE / "logo_warm.png")
    px, n = im.load(), im.width
    lab = [["."] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            r, g, b, a = px[x, y]
            if a < 128:
                continue
            if g > r + 40:
                lab[y][x] = "T" if x < STEM_X and y > 70 else "G"
            elif r > 200 and b < 100:
                lab[y][x] = "Y"
            else:
                lab[y][x] = "K"                         # black: outline or face
    seen = set()                                        # black blobs that don't touch the outside are the face
    for y in range(n):
        for x in range(n):
            if lab[y][x] != "K" or (x, y) in seen:
                continue
            q, pts, outside = deque([(x, y)]), [], False
            seen.add((x, y))
            while q:
                a, b = q.popleft()
                pts.append((a, b))
                for c, d in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
                    if not (0 <= c < n and 0 <= d < n) or lab[d][c] == ".":
                        outside = True
                    elif lab[d][c] == "K" and (c, d) not in seen:
                        seen.add((c, d))
                        q.append((c, d))
            for a, b in pts:
                lab[b][a] = "O" if outside else "F"
    # The shapes look as chunky as they do partly thanks to the outline: give its inner part (up to GROW px)
    # to the nearest shape. That also closes the gaps between stem, leaf and fruit.
    q = deque((x, y, 0) for y in range(n) for x in range(n) if lab[y][x] in "YTG")
    while q:
        x, y, d = q.popleft()
        if d == GROW:
            continue
        for c, e in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= c < n and 0 <= e < n and lab[e][c] == "O":
                lab[e][c] = lab[y][x]
                q.append((c, e, d + 1))
    return [["." if c == "O" else c for c in row] for row in lab]

def grid(n):
    """Shrink the outline-free drawing to n px (fills the square), then shade, highlight and face by rule."""
    lab = shapes()
    N = len(lab)
    pts = [(x, y) for y in range(N) for x in range(N) if lab[y][x] != "."]
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    w, h = max(p[0] for p in pts) - x0 + 1, max(p[1] for p in pts) - y0 + 1
    s = max(w, h) / n
    ox, oy = x0 - (n * s - w) / 2, y0 - (n * s - h) / 2
    k = 6                                               # 6x6 samples per icon pixel
    g = [["."] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            votes = {}
            for j in range(k):
                for i in range(k):
                    sx, sy = int(ox + (x + (i + .5) / k) * s), int(oy + (y + (j + .5) / k) * s)
                    c = lab[sy][sx] if 0 <= sx < N and 0 <= sy < N else "."
                    c = "Y" if c == "F" else c          # the face is placed by hand below
                    votes[c] = votes.get(c, 0) + 1
            if votes.get(".", 0) <= k * k * 0.5:
                votes.pop(".", None)
                g[y][x] = max(votes, key=votes.get)
    fruit = [(x, y) for y in range(n) for x in range(n) if g[y][x] == "Y"]
    cx = sum(p[0] for p in fruit) / len(fruit) + .5
    cy = sum(p[1] for p in fruit) / len(fruit) + .5
    rad = math.sqrt(len(fruit) / math.pi)
    out = lambda x, y: not (0 <= x < n and 0 <= y < n) or g[y][x] == "."
    for x, y in fruit:                                  # gold shade on the lower-right edge
        if (x + .5 - cx) + (y + .5 - cy) > rad * 0.3 and any(out(x + i, y + j) for i, j in ((1, 0), (0, 1), (1, 1))
                                                            + (((2, 0), (0, 2)) if n == 32 else ())):
            g[y][x] = "S"
    # face: centered where the drawing's face is, at fixed symmetric offsets (c is a pixel boundary)
    face = [(x, y) for y in range(N) for x in range(N) if lab[y][x] == "F"]
    c = round((sum(p[0] for p in face) / len(face) - ox) / s)
    ey = round((min(p[1] for p in face) + 10 - oy) / s)
    if n == 32:
        e = [(x, y) for x in (c - 6, c - 5, c + 4, c + 5) for y in (ey, ey + 1)]
        e += [(c - 2, ey + 2), (c + 1, ey + 2), (c - 1, ey + 3), (c, ey + 3)]
        blush = [(c - 8, ey + 2), (c - 7, ey + 2), (c + 6, ey + 2), (c + 7, ey + 2)]
    else:
        e = [(c - 4, ey), (c + 3, ey), (c - 2, ey + 1), (c + 1, ey + 1), (c - 1, ey + 2), (c, ey + 2)]
        blush = [(c - 5, ey + 1), (c + 4, ey + 1)]
    big = n == 32
    hx, hy = round(cx - rad * .55), round(cy - rad * .55)
    high = [(hx, hy), (hx + 1, hy), (hx - 1, hy + 1), (hx, hy + 1), (hx - 1, hy + 2)] if big else [(hx, hy), (hx - 1, hy + 1)]
    for ch, ps in (("H", high), ("b", blush), ("e", e)):
        for x, y in ps:
            if g[y][x] in "YS":
                g[y][x] = ch
    top = min(y for y in range(n) if "T" in g[y])       # stem a bit taller than the drawing's, so it reads at this size
    for y in range(top - STEM_EXTRA[n], top):
        for x in range(n):
            if g[top][x] == "T" and g[y][x] == ".":
                g[y][x] = "T"
    if n == 16:                                         # taper the leaf: at this size it shrinks to a block
        g[0][10] = g[1][9] = "."
    return "\n".join("".join(r).replace("T", "G") for r in g)   # stem in the leaf green: a darker one sank into dark toolbars

def draw(gr):
    rows = gr.split("\n")
    im = Image.new("RGBA", (len(rows), len(rows)), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, c in enumerate(row):
            if c in COLORS:
                im.putpixel((x, y), (*COLORS[c], 255))
    return im

if __name__ == "__main__":
    for n in (16, 32):
        draw(grid(n)).save(HERE / f"icon{n}_warm.png")
    big = Image.open(HERE / "logo_warm.png")              # 48 and 128 are big enough for the drawing itself
    for n in (48, 128):
        big.resize((n, n), Image.LANCZOS).save(HERE / f"icon{n}_warm.png")
