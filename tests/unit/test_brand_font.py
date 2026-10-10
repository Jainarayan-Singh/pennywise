"""APP_BRAND_FONT: a closed list of fonts, each with its own real definition, served from one versioned stylesheet."""
import re
from pathlib import Path

import pytest

from app import create_app
from app.config import ConfigurationError, Settings
from app.config.brand_fonts import BRAND_FONTS, DEFAULT_BRAND_FONT, SUPPORTED_NAMES, find_brand_font, render_css
from tests.conftest import BASE_ENV

STATIC = Path(__file__).resolve().parents[2] / "app" / "static"
ALL = [font.label for font in BRAND_FONTS]


def stylesheet(name):
    app = create_app(Settings.from_env({**BASE_ENV, "APP_BRAND_FONT": name}))
    client = app.test_client()
    html = client.get("/").get_data(as_text=True)
    href = re.search(r'href="(/brand\.css\?v=[0-9a-f]+)"', html).group(1)
    return client, html, href, client.get(href, base_url="http://localhost:5000").get_data(as_text=True)


def test_the_eight_supported_fonts():
    assert ALL == [
        "Segoe Script", "Gabriola", "URW Chancery L", "Monotype Corsiva", "Apple Chancery",
        "Playfair Display Italic", "Cormorant Garamond Italic", "Lora Italic",
    ]
    assert find_brand_font(DEFAULT_BRAND_FONT) is not None


@pytest.mark.parametrize("spelling", ["segoe script", "SEGOE SCRIPT", "  Segoe   Script ", "segoe-script", '"Segoe Script"'])
def test_names_match_whatever_the_spacing_or_case(spelling):
    assert find_brand_font(spelling).label == "Segoe Script"


@pytest.mark.parametrize("bad", ["Comic Sans", "Playfair Display", 'x"; } body { display:none', "../../etc/passwd", "a;b"])
def test_unsupported_fonts_are_rejected_with_the_list_of_valid_ones(bad):
    with pytest.raises(ConfigurationError) as error:
        Settings.from_env({**BASE_ENV, "APP_BRAND_FONT": bad})
    assert "APP_BRAND_FONT" in str(error.value) and all(name in str(error.value) for name in SUPPORTED_NAMES)


def test_unset_means_the_default_font():
    assert Settings.from_env(BASE_ENV).app.brand.label == DEFAULT_BRAND_FONT


@pytest.mark.parametrize("name", ALL)
def test_every_font_produces_its_own_stylesheet(name):
    css = render_css(find_brand_font(name), lambda f: f"/static/fonts/{f}")
    assert f'--font-brand: "{find_brand_font(name).family}"' in css
    assert "--font-brand-style:" in css and "--font-brand-weight:" in css and "--font-brand-scale:" in css


def test_all_eight_stylesheets_are_different():
    sheets = {name: render_css(find_brand_font(name), lambda f: f) for name in ALL}
    assert len(set(sheets.values())) == 8


@pytest.mark.parametrize("name", ["Playfair Display Italic", "Cormorant Garamond Italic", "Lora Italic"])
def test_web_fonts_are_self_hosted_italics_with_their_own_file(name):
    font = find_brand_font(name)
    css = render_css(font, lambda f: f"/static/fonts/{f}")
    assert font.where == "bundled" and (STATIC / "fonts" / font.file).is_file()
    assert (STATIC / "fonts" / font.file).read_bytes()[:4] == b"wOF2"  # a real WOFF2, not an error page
    assert "font-style: italic" in css and f"/static/fonts/{font.file}" in css and "https://" not in css


@pytest.mark.parametrize("name", ["Segoe Script", "Gabriola", "URW Chancery L", "Monotype Corsiva", "Apple Chancery"])
def test_system_fonts_fall_back_to_a_bundled_italic_then_a_generic_serif(name):
    font = find_brand_font(name)
    css = render_css(font, lambda f: f"/static/fonts/{f}")
    stack = re.search(r"--font-brand: ([^;]+);", css).group(1)
    assert stack.startswith(f'"{name}"') and '"Brand Fallback"' in stack and stack.endswith("serif")
    assert '@font-face { font-family: "Brand Fallback"' in css and font.where == "system"
    assert (STATIC / "fonts" / "playfair-display-italic.woff2").is_file()


def test_a_font_name_with_spaces_is_quoted_and_the_page_uses_the_versioned_stylesheet():
    _, html, href, css = stylesheet("Cormorant Garamond Italic")
    assert '"Cormorant Garamond"' in css
    assert href in html and 'rel="preload"' in html and "cormorant-garamond-italic.woff2" in html


def test_system_fonts_need_no_preload():
    _, html, _, _ = stylesheet("Segoe Script")
    assert 'rel="preload"' not in html


def test_the_stylesheet_url_changes_with_the_font_so_a_cache_cannot_hide_the_change():
    hrefs = {name: stylesheet(name)[2] for name in ("Segoe Script", "Gabriola", "Lora Italic")}
    assert len(set(hrefs.values())) == 3


def test_versioned_requests_are_cached_for_good_and_unversioned_ones_are_not():
    client, _, href, _ = stylesheet("Lora Italic")
    assert "immutable" in client.get(href, base_url="http://localhost:5000").headers["Cache-Control"]
    assert client.get("/brand.css", base_url="http://localhost:5000").headers["Cache-Control"] == "no-cache"


def test_brand_name_css_has_no_font_choice_of_its_own():
    layout = (STATIC / "css" / "layout.css").read_text(encoding="utf-8")
    assert "var(--font-brand" in layout and "var(--font-brand-style" in layout and "var(--font-brand-weight" in layout
    for path in (STATIC / "css").rglob("*.css"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"Segoe Script|Gabriola|Chancery|Corsiva|Playfair|Cormorant|Lora", text), path.name


def test_the_name_is_wrapped_the_same_way_everywhere_it_appears(api):
    api.register()
    for path in ("/", "/dashboard"):
        assert 'class="brand-name"' in api.get(path).get_data(as_text=True), path
    assert 'class="splash__name brand-name"' in api.get("/dashboard").get_data(as_text=True)
    assert api.get("/").get_data(as_text=True).count('class="brand-name"') >= 2  # header and footer
