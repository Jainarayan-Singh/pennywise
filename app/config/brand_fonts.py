"""Brand-name typography. APP_BRAND_FONT selects one of the fonts below; it is never used as raw CSS.

Two kinds of font:
  * bundled  - a self-hosted .woff2 in static/fonts/, identical on every device.
  * system   - a font that only exists on some operating systems (Windows, macOS, Linux). If the visitor's
               device doesn't have it, the browser uses the bundled italic below, then a generic serif.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

DEFAULT_BRAND_FONT = "Playfair Display Italic"
FALLBACK_FAMILY = "Brand Fallback"  # the bundled italic that stands in for a missing system font
FALLBACK_FILE = "playfair-display-italic.woff2"
_GENERIC = 'Georgia, "Times New Roman", serif'


@dataclass(frozen=True)
class BrandFont:
    label: str  # the value written in APP_BRAND_FONT
    family: str  # CSS family name
    where: str  # "bundled" or "system"
    weight: int = 400
    scale: float = 1.0  # evens out how big different typefaces look at the same size
    tracking: str = "0"
    file: str | None = None  # bundled .woff2 in static/fonts/
    weight_range: str = "400 700"
    system_names: tuple[str, ...] = ()  # alternative installed names for a system font
    availability: str = ""

    @property
    def stack(self) -> str:
        if self.where == "bundled":
            return f'"{self.family}", {_GENERIC}'
        names = ", ".join(f'"{name}"' for name in (self.family, *self.system_names))
        return f'{names}, "{FALLBACK_FAMILY}", {_GENERIC}'

    @property
    def style(self) -> str:
        return "italic" if self.where == "bundled" else "normal"

    @property
    def files(self) -> tuple[str, ...]:
        return (self.file,) if self.file else (FALLBACK_FILE,)


BRAND_FONTS: tuple[BrandFont, ...] = (
    BrandFont("Segoe Script", "Segoe Script", "system", scale=0.9, availability="Windows"),
    BrandFont("Gabriola", "Gabriola", "system", scale=1.25, availability="Windows (7 and later)"),
    BrandFont("URW Chancery L", "URW Chancery L", "system", scale=1.15, system_names=("Z003",), availability="Linux (URW base35 fonts)"),
    BrandFont("Monotype Corsiva", "Monotype Corsiva", "system", scale=1.15, availability="Windows and macOS with Microsoft Office"),
    BrandFont("Apple Chancery", "Apple Chancery", "system", scale=1.05, availability="macOS and iOS"),
    BrandFont(
        "Playfair Display Italic", "Playfair Display", "bundled", weight=600, tracking="0.01em",
        file="playfair-display-italic.woff2", weight_range="400 900", availability="bundled",
    ),
    BrandFont(
        "Cormorant Garamond Italic", "Cormorant Garamond", "bundled", weight=600, scale=1.2, tracking="0.01em",
        file="cormorant-garamond-italic.woff2", weight_range="300 700", availability="bundled",
    ),
    BrandFont(
        "Lora Italic", "Lora", "bundled", weight=600, tracking="0.01em",
        file="lora-italic.woff2", weight_range="400 700", availability="bundled",
    ),
)

SUPPORTED_NAMES = tuple(font.label for font in BRAND_FONTS)


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


_BY_KEY = {_key(font.label): font for font in BRAND_FONTS}


def find_brand_font(value: str) -> BrandFont | None:
    """Match a configured name ignoring case, spacing, hyphens and quotes ("playfair-display-italic" works)."""
    return _BY_KEY.get(_key(value))


def render_css(font: BrandFont, font_url: Callable[[str], str]) -> str:
    """The stylesheet that makes `font` the brand font. `font_url` turns a file name into its URL."""
    faces = []
    if font.where == "bundled":
        faces.append(_face(font.family, font.file, "italic", font.weight_range, font_url))
    else:  # the bundled italic is the stand-in when this system font isn't installed
        faces.append(_face(FALLBACK_FAMILY, FALLBACK_FILE, "italic", "400 900", font_url))
    variables = (
        f"--font-brand: {font.stack}; --font-brand-style: {font.style}; --font-brand-weight: {font.weight}; "
        f"--font-brand-scale: {font.scale}; --font-brand-tracking: {font.tracking};"
    )
    return "\n".join(faces) + f"\n:root {{ {variables} }}\n"


def _face(family: str, file: str, style: str, weights: str, font_url: Callable[[str], str]) -> str:
    return (
        f'@font-face {{ font-family: "{family}"; src: url("{font_url(file)}") format("woff2"); '
        f"font-style: {style}; font-weight: {weights}; font-display: swap; }}"
    )
