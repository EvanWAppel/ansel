#!/usr/bin/env python3
"""Generate the Ansel app icon.

A dramatic, high-contrast black-and-white mountain-and-moon scene in the
spirit of Ansel Adams (the app's namesake), inside a macOS rounded-square.
Rendered at 4x supersampling for clean edges, then downscaled to 1024.

Run:  uv run --with pillow python make_icon.py
Output: AppIcon.png (1024x1024) in the same directory.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SS = 4                      # supersampling factor
SIZE = 1024
S = SIZE * SS              # working canvas size
HERE = Path(__file__).resolve().parent


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def sky_gradient(w: int, h: int) -> Image.Image:
    """Vertical gradient: near-black at the top easing to pale grey at the horizon."""
    top = (12, 13, 16)
    bottom = (176, 182, 190)
    img = Image.new("RGB", (1, h))
    px = img.load()
    for y in range(h):
        t = (y / (h - 1)) ** 1.35   # keep the sky dark longer, brighten near horizon
        px[0, y] = (
            int(lerp(top[0], bottom[0], t)),
            int(lerp(top[1], bottom[1], t)),
            int(lerp(top[2], bottom[2], t)),
        )
    return img.resize((w, h))


def draw_moon(img: Image.Image) -> None:
    """A luminous moon with a soft glow, high in the sky."""
    cx, cy, r = int(S * 0.335), int(S * 0.30), int(S * 0.105)

    # Soft halo, built on its own layer and blurred.
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([cx - r * 2.4, cy - r * 2.4, cx + r * 2.4, cy + r * 2.4],
               fill=(245, 246, 240, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=r * 0.9))
    img.alpha_composite(glow)

    # The disc itself.
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(247, 247, 241, 255))


def ridge(width: int, base_y: int, peaks: list[tuple[float, float]]) -> list[tuple[int, int]]:
    """Build a closed mountain polygon from (x_frac, y_frac) ridge points."""
    pts = [(int(x * width), int(y * S)) for x, y in peaks]
    return [(0, base_y), *pts, (width, base_y), (width, S), (0, S)]


def draw_mountains(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    base = S

    # Far range — light, hazy, recedes into the sky.
    d.polygon(
        ridge(S, base, [
            (0.00, 0.60), (0.18, 0.50), (0.34, 0.58),
            (0.52, 0.46), (0.70, 0.55), (0.86, 0.48), (1.00, 0.56),
        ]),
        fill=(150, 157, 167),
    )

    # Middle range — mid grey.
    d.polygon(
        ridge(S, base, [
            (0.00, 0.74), (0.22, 0.64), (0.40, 0.72),
            (0.58, 0.60), (0.78, 0.70), (1.00, 0.64),
        ]),
        fill=(83, 89, 99),
    )

    # Foreground peak — near black, the dramatic subject.
    apex_x, apex_y = 0.66, 0.545
    front = [
        (0.00, 0.90), (0.14, 0.82), (0.30, 0.86),
        (0.46, 0.74), (apex_x, apex_y), (0.82, 0.70), (1.00, 0.80),
    ]
    d.polygon(ridge(S, base, front), fill=(17, 18, 20))

    # Snowcap: a bright sunlit facet just below the apex.
    ax, ay = apex_x * S, apex_y * S
    snow = [
        (ax, ay),
        (ax - S * 0.055, ay + S * 0.085),
        (ax - S * 0.018, ay + S * 0.058),
        (ax + S * 0.010, ay + S * 0.092),
        (ax + S * 0.040, ay + S * 0.060),
        (ax + S * 0.072, ay + S * 0.10),
    ]
    d.polygon(snow, fill=(238, 240, 236))


def rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def main() -> None:
    canvas = sky_gradient(S, S).convert("RGBA")
    draw_moon(canvas)
    draw_mountains(canvas)

    # Subtle darkening vignette at the corners for depth.
    vig = Image.new("L", (S, S), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse([-S * 0.15, -S * 0.15, S * 1.15, S * 1.15], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(S * 0.12))
    dark = Image.new("RGBA", (S, S), (0, 0, 0, 120))
    canvas = Image.composite(canvas, Image.alpha_composite(canvas, dark), vig)

    # Round the corners (Apple squircle approximation ~18% radius).
    canvas.putalpha(rounded_mask(S, int(S * 0.185)))

    out = canvas.resize((SIZE, SIZE), Image.LANCZOS)
    dest = HERE / "AppIcon.png"
    out.save(dest)
    print(f"✓ wrote {dest}")


if __name__ == "__main__":
    main()
