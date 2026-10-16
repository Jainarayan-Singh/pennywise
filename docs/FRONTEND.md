# Frontend conventions

Plain HTML (Jinja), CSS and ES modules. No framework, no build step.

## Rules (enforced by `tests/unit/test_site.py`)
- Templates contain markup only: no inline `<script>`, event handlers, `<style>` or `style=` attributes. A strict CSP (`script-src 'self'; style-src 'self'`) backs this up.
- All colours live in `static/css/tokens.css`. Other stylesheets may only reference `var(--token)`.
- JavaScript never calls `alert`/`confirm`/`prompt`, never uses `innerHTML` or `cssText`, and every relative import must resolve. The only style writes allowed are CSS custom properties (`style.setProperty("--name", …)`), used to position popups.
- Every page must work in both themes and at 375px, 768px and desktop widths.

## Typography
Two families, one rule. **Source Serif 4** (headings 1 and 2, the page title, the product name) gives the editorial character; **DM Sans** carries everything that works: body copy, labels, cards, controls, tables. Both are self-hosted (`static/fonts`, declared in `css/base.css`); they are open-licence stand-ins in the spirit of a serif/grotesque pairing, not any company's proprietary fonts. Sizes come from the `--text-*` tokens (`--text-3xl` is the fluid display size); headings 3 and 4 are sans, semibold. Never write a font name in CSS.

## Emails
Transactional mail is rendered from `templates/emails/` (`_layout.html`, `_button.html`, and a `.html` + `.txt` pair per message) by `services/email_messages.py`. Each message has a plain-text body and a table-based HTML body with inline styles (email clients ignore stylesheets), one button, and the raw link beneath it. Email colours are the only place raw hex values are allowed, and they use the Sunset palette. In development (no email provider) the outbox writes both a `.txt` and a `.html` file to `instance/outbox`; open the `.html` to see the message.

## Layouts
- `layouts/public.html`: landing, sign-in, reset password. Public header and footer.
- `layouts/app.html`: every signed-in page. A thin 3rem top bar (sidebar toggle, brand, theme toggle, user menu) over a docked sidebar (13.75rem, or a 3.25rem icon rail) and the page. Each page starts with a `.page-head` (title, plus the page's own actions). Child templates fill `page_title`, `page_actions`, `main_attrs` and `content`. The current page is marked with `aria-current="page"` in `components/sidebar.html`, which links only to implemented pages (Quick add appears only when AI is configured).
- Both extend `base.html`, which provides toasts, the confirm dialog, the icon sprite and `core/app.js`. Add a new icon as a `<symbol>` in `components/shell.html`.

## Stylesheets (`static/css/`)
| File | Role |
|---|---|
| `tokens.css` | Design tokens: colour (both themes via `light-dark()`), type, spacing, radii, shadows, z-index, motion, control sizes. The palette, DM Sans type scale, 10px radii and shell metrics follow the Smart AI Exam Portal (`static/theme.css`) |
| `base.css` | Reset, typography, focus ring, utilities |
| `layout.css` | Public header/footer, app shell (sidebar, top bar, drawer), grids |
| `components.css` | Buttons, form controls, cards, badges, alerts, tables, menus, modals, toasts, skeletons, states, tooltips |
| `pickers.css` | Custom dropdown and date picker |
| `pages/*.css` | Only what is unique to one page |

Add a token before adding a one-off value. Add a component class before copying markup between pages.

## Themes
Five themes, as in the Exam Portal: Paper (light), Dark, Midnight, Emerald, Sunset. Light and Dark declare every colour once as `light-dark(light, dark)`; Midnight, Emerald and Sunset are `:root[data-theme="…"]` blocks at the end of `tokens.css` that override the surface, text and accent tokens. `<html data-theme>` selects the theme; with none saved the default is Sunset. `js/core/theme-init.js` is a tiny *blocking external* script in `<head>` that sets the attribute before first paint (no flash); `js/core/theme.js` handles the picker (`theme_menu()` macro, items carry `data-theme-option`) and stores the choice in `localStorage["theme"]`. To add a theme: one token block, one `--swatch-*` dot, one entry in the macro, the two JS lists.

## Shared UI (use these, don't reimplement)
- **Buttons:** `.btn` + `--primary | --secondary | --outline | --ghost | --danger | --danger-ghost`, sizes `--sm | --lg`, `--icon`, `--block`; loading via the `data-loading` attribute.
- **Form macros** (`templates/components/macros.html`): `field`, `password_field`, `select_field`, `date_field`, `form_dialog`, `icon`.
- **Dropdown:** `select_field` renders a native `<select data-dropdown>`, which stays the source of truth (forms, validation, mobile fallback). `components/dropdown.js` replaces it with an accessible listbox: keyboard (arrows, Home/End, type-ahead, Enter, Escape), search when there are many options, viewport-aware placement, disabled/empty/error states, long labels. Populate with `fillSelect` and set with `setSelectValue` from `components/form-helpers.js`; both keep the custom control in sync.
- **Date picker:** `date_field` renders a hidden `<input name=…>` plus `data-datepicker`. `components/datepicker.js` provides a calendar with month/year navigation (using the shared dropdown), today/selected/disabled states, `min`/`max`, keyboard navigation, locale-aware labels and a clear button. Dates are plain `YYYY-MM-DD` strings, so there is no timezone drift. Set values with `setDateValue`.
- **Popups:** `components/popup.js` positions dropdown and calendar panels in the top layer (`popover`), so they work inside dialogs without z-index fights, flip above when there is no room below and close on Escape without closing the dialog.
- **Modals:** `<dialog class="modal">` is centered with a maximum width and scrolls internally (`modal--sm`, `modal--wide`). `form_dialog(id, title, submit_label, size)` builds the standard form modal (title, inline alert, Cancel/Save, busy state). The same modal serves Add and Edit transaction. Close buttons use `data-dialog-close`.
- **Confirm:** `confirmAction({ title, message, confirmLabel, tone, action })` from `components/dialog.js` handles focus, Escape, a busy state and errors. Use it for destructive or hard-to-undo actions, including sign-out.
- **Loading screen:** it uses the same theme tokens as every page (`--color-bg`, `--color-text`, `--color-primary`...), so it is automatically in the selected theme; it has no palette of its own.
- **Charts:** `components/charts.js` draws the dashboard's bar, area and donut charts as plain SVG (no library; the CSP also forbids CDN scripts). Colours come from `--chart-*` tokens (income emerald, expenses coral, savings teal), entrance animation is CSS, tooltips and keyboard focus are built in, and `countUp` animates summary figures. Charts take the server's decimal strings; the browser never calculates money.
- **Sidebar:** from 48rem up the sidebar folds to an icon rail (`html[data-sidebar="collapsed"]`, stored in `localStorage["sidebar"]` and applied before first paint by `theme-init.js`). Every nav control needs `data-label` and a `.nav-item__label` span; the rail shows the label as a tooltip. Below 48rem it is an off-canvas drawer that opens under the top bar, scrolls as a whole, and locks the page behind it; the rail is ignored there.
- **Phones first:** design for 320px. Reuse the shared rules instead of page-specific patches: small controls grow to 40px on touch (end of `components.css`), tables become compact cards below 48rem (`td` cells carry `data-label`; empty meta cells get `.is-empty`), long filter groups sit behind a toggle (`.filters__fields`), amounts size themselves from their container (`cqi`), and flex items that hold text need `min-width: 0` so nothing pushes the page wider than the screen.
- **Brand name:** wrap the product name in `<span class="brand-name">`; its font, style, weight and size come from `APP_BRAND_FONT` through the versioned `/brand.css` (catalog in `app/config/brand_fonts.py`). Never write a font name in CSS for it.
- **Brand logo:** use the `brand_logo()` macro (static `favicon.png`); do not draw a text or symbol logo.
- **Page actions:** wrap the text in `<span class="btn__label">` (plus an `aria-label`) so it collapses to an icon on phones.
- **Toasts:** `toast.success|error|warning|info(message)` from `components/toast.js`. Use inline `.field__error` / `.alert` for validation.
- **Loading / empty / error:** `showSkeleton`, `showState` from `components/state.js`.
- **Forms in JS:** `components/form-helpers.js` (`setBusy`, `showFieldErrors`, `setAlert`, `fillSelect`, `setSelectValue`, `setDateValue`). Read `FormData` before `setBusy`, because disabled controls are omitted.
- **API calls:** `services/api-client.js` (`getJson`, `postJson`, `deleteJson`, `requestJson`). It adds CSRF, a timeout and uniform errors.
- **Sign-out:** any element with `data-action="sign-out"` opens the confirmation; `core/logout.js` revokes the session on the server, clears client state and shows a transition overlay while redirecting to the landing page.

## Adding a page
1. Route + template extending `layouts/app.html` (or `layouts/public.html`); protect the route with `page_login_required`.
2. `static/js/pages/<name>.js` as a `type="module"` script in `{% block scripts %}`; page CSS only if needed.
3. Link it from `components/sidebar.html` only once it works.
