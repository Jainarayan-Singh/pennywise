const COMPACT = window.matchMedia("(max-width: 63.99rem)");

/** On tablet and mobile the sidebar is an off-canvas drawer; on desktop it is always visible and this does nothing. */
export function initNavDrawer() {
    const sidebar = document.getElementById("sidebar");
    if (!sidebar) return;
    const backdrop = document.querySelector("[data-drawer-backdrop]");
    const toggles = document.querySelectorAll("[data-nav-toggle]");
    const main = document.querySelector(".app-main");
    const opener = document.querySelector("[data-nav-toggle][aria-controls]");
    let returnFocus = null;

    function setOpen(open) {
        sidebar.toggleAttribute("data-open", open);
        backdrop.toggleAttribute("data-open", open);
        document.body.toggleAttribute("data-drawer-open", open);
        opener.setAttribute("aria-expanded", String(open));
        main.inert = open; // nothing behind the open drawer can be reached
        if (open) {
            returnFocus = document.activeElement;
            sidebar.querySelector("a")?.focus();
        } else {
            returnFocus?.focus();
            returnFocus = null;
        }
    }

    for (const toggle of toggles) toggle.addEventListener("click", () => setOpen(!sidebar.hasAttribute("data-open")));
    backdrop.addEventListener("click", () => setOpen(false));
    sidebar.addEventListener("click", (event) => {
        if (COMPACT.matches && event.target.closest("a")) setOpen(false);
    });
    sidebar.addEventListener("keydown", (event) => {
        if (!sidebar.hasAttribute("data-open")) return;
        if (event.key === "Escape") {
            setOpen(false);
            return;
        }
        if (event.key !== "Tab") return;
        const focusable = [...sidebar.querySelectorAll("a[href], button:not(:disabled)")].filter((node) => node.offsetParent !== null);
        const first = focusable[0];
        const last = focusable.at(-1);
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });
    COMPACT.addEventListener("change", (event) => {
        if (!event.matches && sidebar.hasAttribute("data-open")) setOpen(false);
    });
}

const DESKTOP = window.matchMedia("(min-width: 64rem)");

/**
 * Desktop only: fold the sidebar to an icon rail and back. The state lives on <html data-sidebar> (set before
 * first paint by theme-init.js) and in localStorage. In the rail each control shows its name as a tooltip.
 */
export function initSidebarCollapse() {
    const toggle = document.querySelector("[data-sidebar-toggle]");
    if (!toggle) return;
    const root = document.documentElement;
    const labelled = document.querySelectorAll("#sidebar [data-label]");

    function apply() {
        const collapsed = root.getAttribute("data-sidebar") === "collapsed";
        const railShown = collapsed && DESKTOP.matches;
        toggle.setAttribute("aria-expanded", String(!collapsed));
        toggle.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
        toggle.dataset.label = toggle.getAttribute("aria-label");
        for (const item of labelled) {
            if (railShown) item.setAttribute("data-tooltip", item.dataset.label.replace("&amp;", "&"));
            else item.removeAttribute("data-tooltip");
        }
    }

    toggle.addEventListener("click", () => {
        const collapsed = root.getAttribute("data-sidebar") !== "collapsed";
        if (collapsed) root.setAttribute("data-sidebar", "collapsed");
        else root.removeAttribute("data-sidebar");
        try {
            if (collapsed) localStorage.setItem("sidebar", "collapsed");
            else localStorage.removeItem("sidebar");
        } catch {
            // The choice still applies for this visit.
        }
        apply();
    });
    DESKTOP.addEventListener("change", apply);
    apply();
}