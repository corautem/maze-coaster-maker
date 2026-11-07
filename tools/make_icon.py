# Maze Coaster Maker: circular-maze coasters for 3D printing.
# Copyright (C) 2026 corautem
# SPDX-License-Identifier: GPL-3.0-or-later
"""Renders the app icon, a classical-labyrinth coaster readable at 16 px, into a folder:

    app.ico  Windows (16 to 256 px)
    app.png  macOS and Linux (512 px); PyInstaller turns it into the macOS .icns

    python tools/make_icon.py [folder]      (default: build)
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import coaster_gen as cg  # noqa: E402

SIZE = 1024  # draw large, let Pillow scale down for each icon size


def render():
    d = cg.Design(shape="circle", pattern="classical", size=100, rim=6, wall=4, gap=4, center_d=40)
    outline = cg.make_outline(d)
    channels, _, _ = cg.classical_channels(outline.polygon().buffer(-d.rim), d)
    scale = SIZE / 102

    def px(points):
        return [(SIZE / 2 + x * scale, SIZE / 2 - y * scale) for x, y in points]

    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = outline.circle_r * scale
    draw.ellipse((SIZE / 2 - r, SIZE / 2 - r, SIZE / 2 + r, SIZE / 2 + r), fill="#8a7556")
    r -= 16
    draw.ellipse((SIZE / 2 - r, SIZE / 2 - r, SIZE / 2 + r, SIZE / 2 + r), fill="#e6d7b9")
    for loop in cg.geometry_loops(channels):
        draw.polygon(px(cg.flatten_loop(loop)), fill="#3a2e27")
    return img


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build"
    out.mkdir(parents=True, exist_ok=True)
    img = render()
    img.save(out / "app.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    img.resize((512, 512), Image.LANCZOS).save(out / "app.png")
    print(f"icons: {out / 'app.ico'}, {out / 'app.png'}")


if __name__ == "__main__":
    main()
