import { initDatePickers } from "../components/datepicker.js";
import { initDialogs } from "../components/dialog.js";
import { initDropdowns } from "../components/dropdown.js";
import { initMenus } from "../components/menu.js";
import { initPasswordToggles } from "../components/password-field.js";
import { getJson } from "../services/api-client.js";
import { initNavDrawer, initSidebarCollapse } from "./nav-drawer.js";
import { finishArrival, hidePageTransition } from "./page-transition.js";
import { signOut } from "./logout.js";
import { initTheme } from "./theme.js";

initTheme();
initMenus();
initDialogs();
initPasswordToggles();
initDropdowns();
initDatePickers();
initNavDrawer();
initSidebarCollapse();
finishArrival();

document.addEventListener("click", (event) => {
    if (event.target.closest('[data-action="sign-out"]')) signOut();
});

// Back/forward can restore a page from the browser's cache without asking the server.
// Re-check the session so a signed-out user never keeps seeing an authenticated page.
window.addEventListener("pageshow", async (event) => {
    if (!event.persisted) return;
    hidePageTransition();
    if (!document.body.hasAttribute("data-authenticated")) return;
    try {
        const { authenticated } = await getJson("/api/v1/auth/session");
        if (!authenticated) window.location.replace("/login");
    } catch {
        // Offline: leave the page; any action will be rejected by the server anyway.
    }
});

if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    document.querySelectorAll(".brand__video").forEach((video) => video.pause());
}
