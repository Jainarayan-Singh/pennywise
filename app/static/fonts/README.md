# Bundled brand fonts

Self-hosted so production never depends on an external font service. Latin subsets, variable weight, italic.

| File | Font | Licence |
|---|---|---|
| `playfair-display-italic.woff2` | Playfair Display Italic | SIL Open Font License 1.1 |
| `cormorant-garamond-italic.woff2` | Cormorant Garamond Italic | SIL Open Font License 1.1 |
| `lora-italic.woff2` | Lora Italic | SIL Open Font License 1.1 |

Source: Google Fonts (fonts.gstatic.com), https://fonts.google.com. `playfair-display-italic.woff2` is also the stand-in
shown when a selected system font is not installed on the visitor's device. Which font is used is decided by
`APP_BRAND_FONT` (see `docs/CONFIGURATION.md`); the catalog lives in `app/config/brand_fonts.py`.