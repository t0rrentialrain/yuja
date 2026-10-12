"""Comparison sheet of logo variants at full size and toolbar sizes, light and dark.
Usage: python yuja/logo/compare.py lemon warm   (writes compare.png)"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
LABELS = {"lemon": "Lemon yellow, smooth (your drawing)  #ffef02", "golden": "Golden yuja, smooth  #ffc21a",
          "warm": "Warm yellow, bumpy peel  #ffdc0a"}
names = sys.argv[1:] or ["lemon", "warm"]
font = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 22)
small = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 15)
W = 1100
sheet = Image.new("RGBA", (W, len(names) * 360 + 20), (250, 250, 247, 255))
dr = ImageDraw.Draw(sheet)
for row, name in enumerate(names):
    y0 = 10 + row * 360
    dr.text((20, y0), LABELS[name], font=font, fill=(40, 40, 40))
    sheet.alpha_composite(Image.open(HERE / f"logo_{name}.png").resize((280, 280), Image.LANCZOS), (20, y0 + 40))
    for k, (bg, fg, cap) in enumerate((((255, 255, 255), (60, 60, 60), "light toolbar"), ((53, 54, 58), (220, 220, 220), "dark toolbar"))):
        x0, yb = 340, y0 + 50 + k * 150
        dr.rounded_rectangle((x0, yb, W - 20, yb + 130), 14, fill=bg)
        x = x0 + 20
        for s in (16, 32, 48, 128):
            sheet.alpha_composite(Image.open(HERE / f"icon{s}_{name}.png"), (x, yb + 65 - s // 2 if s < 128 else yb + 1))
            x += s + 25
        x += 10
        for s in (16, 32):                               # the pixel-art sizes blown up
            sheet.alpha_composite(Image.open(HERE / f"icon{s}_{name}.png").resize((112, 112), Image.NEAREST), (x, yb + 9))
            x += 130
        dr.text((W - 130, yb + 105), cap, font=small, fill=fg)
sheet.convert("RGB").save(HERE / "compare.png")
