const STORAGE_KEY = "theme";
const THEMES = ["light", "dark", "midnight", "emerald", "sunset"];
const DEFAULT_THEME = "sunset";
const root = document.documentElement;

function storeTheme(theme) {
    try {
        localStorage.setItem(STORAGE_KEY, theme);
    } catch {
        // Private mode or blocked storage: the choice simply won't persist.
    }
}

function applyTheme(theme) {
    root.dataset.theme = theme;
    for (const option of document.querySelectorAll("[data-theme-option]")) {
        option.setAttribute("aria-checked", String(option.dataset.themeOption === theme));
    }
}

/** Every `[data-theme-option="name"]` menu item switches the whole app to that theme and remembers it. */
export function initTheme() {
    applyTheme(THEMES.includes(root.dataset.theme) ? root.dataset.theme : DEFAULT_THEME);

    for (const option of document.querySelectorAll("[data-theme-option]")) {
        option.addEventListener("click", () => {
            const theme = option.dataset.themeOption;
            storeTheme(theme);
            applyTheme(theme);
        });
    }
}
