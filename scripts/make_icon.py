"""Draw the brand icon of the integration.

Run: uv run --with pillow python scripts/make_icon.py

The icon is an original drawing: a rounded badge, a clock dial with the
first quarter hour marked, and a lightning bolt. It writes icon.png (256 px)
and icon@2x.png (512 px) into custom_components/elektro_15min_average/brand/.
The background around the badge is transparent. The badge is dark, so the
icon reads on light and dark pages.
"""

from pathlib import Path

from PIL import Image, ImageDraw

SCALE = 4
BADGE = (22, 56, 74, 255)  # dark petrol
RING = (255, 255, 255, 255)
DIAL = (44, 92, 114, 255)  # the full hour
QUARTER = (64, 196, 160, 255)  # the 15 minutes
BOLT = (255, 200, 40, 255)
BOLT_EDGE = (22, 56, 74, 255)


def draw(size):
    big = size * SCALE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def p(x, y):
        return (x * big / 100, y * big / 100)

    d.rounded_rectangle([p(6, 6), p(94, 94)], radius=big * 0.22, fill=BADGE)
    d.rounded_rectangle(
        [p(6, 6), p(94, 94)], radius=big * 0.22, outline=RING, width=int(big * 0.02)
    )
    box = [p(20, 20), p(80, 80)]
    d.ellipse(box, fill=DIAL)
    d.pieslice(box, start=-90, end=0, fill=QUARTER)  # 12 to 3 o'clock = 15 min
    # tick marks at 12, 3, 6, 9
    for x1, y1, x2, y2 in [
        (50, 21, 50, 27),
        (79, 50, 73, 50),
        (50, 79, 50, 73),
        (21, 50, 27, 50),
    ]:
        d.line([p(x1, y1), p(x2, y2)], fill=RING, width=int(big * 0.02))
    bolt = [(54, 26), (36, 54), (48, 54), (42, 76), (64, 46), (52, 46), (58, 26)]
    d.polygon(
        [p(x, y) for x, y in bolt], fill=BOLT, outline=BOLT_EDGE, width=int(big * 0.012)
    )
    return img.resize((size, size), Image.LANCZOS)


OUT = (
    Path(__file__).parent.parent
    / "custom_components"
    / "elektro_15min_average"
    / "brand"
)

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    draw(256).save(OUT / "icon.png")
    draw(512).save(OUT / "icon@2x.png")
