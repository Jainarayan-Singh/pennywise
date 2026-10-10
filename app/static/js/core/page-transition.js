// Keep in step with --splash-duration in tokens.css: long enough to be noticed, short enough not to be a wait.
const MIN_VISIBLE_MS = 1700;
const STALL_MS = 10000;
const LEAVE_MS = 520;
const ARRIVAL_KEY = "transition-arrival";

const overlay = () => document.getElementById("page-transition");

export function hidePageTransition() {
    const element = overlay();
    element.hidden = true;
    element.classList.remove("is-leaving");
    document.documentElement.removeAttribute("data-arrival");
}

/**
 * Cover the page with the loading screen, keep it up for at least MIN_VISIBLE_MS, then navigate. The next page
 * starts with the screen already in place and fades it out. If navigation stalls, the screen is removed and
 * `onStall` runs, so the user is never left on it. Use only for sign-out style transitions.
 */
export function navigateWithTransition(url, message, onStall) {
    const element = overlay();
    document.getElementById("page-transition-text").textContent = message;
    element.hidden = false;
    setTimeout(() => {
        try {
            sessionStorage.setItem(ARRIVAL_KEY, "1");
        } catch {
            // Without storage the next page simply loads normally.
        }
        window.location.replace(url);
        setTimeout(() => {
            hidePageTransition();
            onStall?.();
        }, STALL_MS);
    }, MIN_VISIBLE_MS);
}

/** On the page we navigated to: fade the loading screen out (theme-init.js already showed it before first paint). */
export function finishArrival() {
    if (!document.documentElement.hasAttribute("data-arrival")) return;
    overlay().classList.add("is-leaving");
    setTimeout(hidePageTransition, LEAVE_MS);
}
