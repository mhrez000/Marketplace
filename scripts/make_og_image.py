"""One-off: generate the default Open Graph share image (1200x630).
Run: python scripts/make_og_image.py"""
import os

from PIL import Image, ImageDraw, ImageFont

NAVY = (47, 65, 86)
BEIGE = (245, 239, 235)
TEAL = (86, 124, 141)
SKY = (200, 217, 230)

OUT = os.path.join(os.path.dirname(__file__), "..", "static", "img", "og-default.png")
os.makedirs(os.path.dirname(OUT), exist_ok=True)


def font(paths, size):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


serif = font(["C:/Windows/Fonts/georgiab.ttf", "georgiab.ttf", "C:/Windows/Fonts/georgia.ttf"], 150)
sans = font(["C:/Windows/Fonts/arial.ttf", "arial.ttf"], 46)
sans_sm = font(["C:/Windows/Fonts/arial.ttf", "arial.ttf"], 34)

img = Image.new("RGB", (1200, 630), NAVY)
d = ImageDraw.Draw(img)

# Aperture mark, top-left.
cx, cy, r = 130, 120, 46
d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=BEIGE, width=6)
d.ellipse([cx - 18, cy - 18, cx + 18, cy + 18], fill=TEAL)

# Wordmark.
d.text((100, 230), "Lens", font=serif, fill=BEIGE)

# Tagline.
d.text((104, 410), "Find & book Melbourne's best", font=sans, fill=SKY)
d.text((104, 466), "photographers & videographers", font=sans, fill=SKY)

# Footer strip.
d.rectangle([0, 600, 1200, 630], fill=TEAL)
d.text((104, 548), "Built in Australia  ·  no per-lead fees", font=sans_sm, fill=(200, 217, 230))

img.save(OUT, "PNG", optimize=True)
print("wrote", os.path.abspath(OUT), img.size)
