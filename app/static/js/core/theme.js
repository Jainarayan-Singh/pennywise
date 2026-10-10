const STORAGE_KEY = "theme";
const root = document.documentElement;
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");

function readStoredTheme() {
    try {
        const value = localStorage.getItem(STORAGE_KEY);
        return value === "light" || value === "dark" ? value : null;
    } catch {
        return null;
    }
}

function storeTheme(theme) {
    try {
        localStorage.setItem(STORAGE_KEY, theme);
    } catch {
        // Private mode or blocked storage: the choice simply won't persist.
    }
}

function applyTheme(theme) {
    root.dataset.theme = theme;
    const next = theme === "dark" ? "light" : "dark";
    for (const button of document.querySelectorAll("[data-theme-toggle]")) {
        const label = `Switch to ${next} theme`;
        button.setAttribute("aria-label", label);
        button.dataset.tooltip = label;
    }
}

export function initTheme() {
    applyTheme(root.dataset.theme === "dark" ? "dark" : "light");

    for (const button of document.querySelectorAll("[data-theme-toggle]")) {
        button.addEventListener("click", () => {
            const next = root.dataset.theme === "dark" ? "light" : "dark";
            storeTheme(next);
            applyTheme(next);
        });
    }

    // Follow the OS only while the user hasn't made an explicit choice.
    systemDark.addEventListener("change", (event) => {
        if (!readStoredTheme()) applyTheme(event.matches ? "dark" : "light");
    });
}
