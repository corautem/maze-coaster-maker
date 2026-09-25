"""Renders the app icon (default build/app.ico): a classical-labyrinth coaster readable at 16 px."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import coaster_gen as cg  # noqa: E402

SIZE = 1024  # draw large, let Pillow downscale for each icon size

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

out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "app.ico"
out.parent.mkdir(parents=True, exist_ok=True)
img.save(out, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
print(f"icon: {out}")
