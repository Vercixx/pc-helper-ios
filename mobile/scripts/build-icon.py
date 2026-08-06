#!/usr/bin/env python3
"""
Draw the app icon: a desktop monitor with a power glyph on its screen.

The geometry lives here once and the three appearance variants differ only by
palette, so light, dark and tinted can never drift out of alignment with each
other. Run this after changing anything below:

    python3 scripts/build-icon.py

It writes assets/icon-{light,dark,tinted}.svg and rasterises each to a matching
1024x1024 PNG. CI never runs this -- `expo prebuild` consumes the PNGs -- so
the generated files are committed alongside the script.

Why three PNGs rather than an Icon Composer `.icon` bundle: Icon Composer is
macOS-only. This gets the appearance variants and the correct mask; it does not
get iOS 26's layered specular pass, which only a `.icon` bundle can carry.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

SIZE = 1024
ASSETS = Path(__file__).resolve().parent.parent / "assets"

# --- Geometry -----------------------------------------------------------
# Full-bleed: iOS applies the squircle mask itself, so nothing here is rounded
# to anticipate it. The monitor is deliberately chunky -- a fine bezel turns to
# mush at the 40pt the icon is actually looked at.

BEZEL = dict(x=192, y=236, w=640, h=452, r=52)
SCREEN = dict(x=232, y=276, w=560, h=372, r=28)
NECK = dict(x=472, y=688, w=80, h=52)
BASE = dict(x=372, y=740, w=280, h=44, r=22)

GLYPH_CX, GLYPH_CY = 512.0, 478.0
GLYPH_R = 108.0
GLYPH_STROKE = 40.0
# Half-width of the gap at the top of the ring, where the bar passes through.
GLYPH_GAP_DEG = 42.0


def power_arc() -> str:
    """The broken ring of the ⏻ glyph, as an SVG arc path."""
    start = math.radians(-90 + GLYPH_GAP_DEG)
    end = math.radians(-90 - GLYPH_GAP_DEG) + 2 * math.pi
    x1 = GLYPH_CX + GLYPH_R * math.cos(start)
    y1 = GLYPH_CY + GLYPH_R * math.sin(start)
    x2 = GLYPH_CX + GLYPH_R * math.cos(end)
    y2 = GLYPH_CY + GLYPH_R * math.sin(end)
    # Sweeps the long way round (everything but the gap), clockwise.
    return f"M {x1:.2f} {y1:.2f} A {GLYPH_R} {GLYPH_R} 0 1 1 {x2:.2f} {y2:.2f}"


# --- Palettes -----------------------------------------------------------
# `tinted` must be a *value* composition on black: iOS throws the hue away and
# re-tints by luminance, so what matters there is light-versus-dark, not colour.

PALETTES = {
    "light": dict(
        bg_top="#0A84FF",  # the accent the widget already uses
        bg_bottom="#0060DF",
        chassis="#FFFFFF",
        screen="#0A2A5E",
        glyph="#FFFFFF",
    ),
    "dark": dict(
        bg_top="#0A2540",
        bg_bottom="#07131F",
        chassis="#E8EDF2",
        screen="#071A2E",
        glyph="#0A84FF",
    ),
    "tinted": dict(
        bg_top="#000000",
        bg_bottom="#000000",
        chassis="#E6E6E6",
        screen="#1A1A1A",
        glyph="#FFFFFF",
    ),
}


def svg(palette: dict[str, str]) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{palette['bg_top']}"/>
      <stop offset="1" stop-color="{palette['bg_bottom']}"/>
    </linearGradient>
  </defs>

  <rect width="{SIZE}" height="{SIZE}" fill="url(#bg)"/>

  <rect x="{NECK['x']}" y="{NECK['y']}" width="{NECK['w']}" height="{NECK['h']}" fill="{palette['chassis']}"/>
  <rect x="{BASE['x']}" y="{BASE['y']}" width="{BASE['w']}" height="{BASE['h']}" rx="{BASE['r']}" fill="{palette['chassis']}"/>

  <rect x="{BEZEL['x']}" y="{BEZEL['y']}" width="{BEZEL['w']}" height="{BEZEL['h']}" rx="{BEZEL['r']}" fill="{palette['chassis']}"/>
  <rect x="{SCREEN['x']}" y="{SCREEN['y']}" width="{SCREEN['w']}" height="{SCREEN['h']}" rx="{SCREEN['r']}" fill="{palette['screen']}"/>

  <g stroke="{palette['glyph']}" stroke-width="{GLYPH_STROKE}" stroke-linecap="round" fill="none">
    <path d="{power_arc()}"/>
    <line x1="{GLYPH_CX}" y1="348" x2="{GLYPH_CX}" y2="462"/>
  </g>
</svg>
"""


def main() -> int:
    if not shutil.which("rsvg-convert"):
        print("rsvg-convert not found (Arch: librsvg)", file=sys.stderr)
        return 1

    for name, palette in PALETTES.items():
        svg_path = ASSETS / f"icon-{name}.svg"
        png_path = ASSETS / f"icon-{name}.png"
        svg_path.write_text(svg(palette))
        subprocess.run(
            ["rsvg-convert", "-w", str(SIZE), "-h", str(SIZE), str(svg_path), "-o", str(png_path)],
            check=True,
        )
        print(f"{svg_path.name} -> {png_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
