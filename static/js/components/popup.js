const GAP = 6;
const MARGIN = 8;

/**
 * Shows `panel` (a `popover="manual"` element) next to `trigger`. Popovers render in the browser's top layer, so
 * they are never clipped by a scrolling modal body and always sit above it. The panel flips above the trigger
 * when there is no room below, and is kept inside the viewport. Small screens use a bottom sheet (see pickers.css).
 */
export function createPopup({ trigger, panel, preferredHeight = 320, onDismiss }) {
    let isOpen = false;

    function place() {
        const rect = trigger.getBoundingClientRect();
        const viewWidth = window.innerWidth;
        const viewHeight = window.visualViewport?.height ?? window.innerHeight; // shrinks when a phone keyboard opens

        // Measure the panel as it really is (a calendar is wider than its trigger), then fit it to the screen.
        panel.style.setProperty("--popup-width", `${Math.min(rect.width, viewWidth - 2 * MARGIN)}px`);
        panel.style.setProperty("--popup-max-height", "none");
        const width = panel.offsetWidth;
        const natural = Math.min(panel.offsetHeight, preferredHeight);

        let left = rect.left;
        if (left + width > viewWidth - MARGIN) left = rect.right - width; // grow leftwards from the trigger's right edge
        left = Math.min(Math.max(MARGIN, left), Math.max(MARGIN, viewWidth - width - MARGIN));

        const below = viewHeight - rect.bottom - GAP - MARGIN;
        const above = rect.top - GAP - MARGIN;
        const placement = natural <= below || below >= above ? "bottom" : "top";
        const room = placement === "bottom" ? below : above;

        panel.dataset.placement = placement;
        panel.style.setProperty("--popup-left", `${left}px`);
        panel.style.setProperty("--popup-max-height", `${Math.max(160, Math.min(natural, room))}px`);
        if (placement === "bottom") panel.style.setProperty("--popup-top", `${rect.bottom + GAP}px`);
        else panel.style.setProperty("--popup-bottom", `${viewHeight - rect.top + GAP}px`);
    }

    function onPointerDown(event) {
        if (!panel.contains(event.target) && !trigger.contains(event.target)) onDismiss?.();
    }

    function onScroll(event) {
        if (!panel.contains(event.target)) place();
    }

    function show() {
        if (isOpen) return;
        trigger.scrollIntoView({ block: "nearest" }); // a field scrolled out of a long form comes into view first
        panel.showPopover();
        isOpen = true;
        place();
        document.addEventListener("pointerdown", onPointerDown, true);
        document.addEventListener("scroll", onScroll, true);
        window.addEventListener("resize", place);
        window.visualViewport?.addEventListener("resize", place);
    }

    function hide() {
        if (!isOpen) return;
        isOpen = false;
        if (panel.matches(":popover-open")) panel.hidePopover();
        document.removeEventListener("pointerdown", onPointerDown, true);
        document.removeEventListener("scroll", onScroll, true);
        window.removeEventListener("resize", place);
        window.visualViewport?.removeEventListener("resize", place);
    }

    // A popup left open inside a dialog must not outlive it.
    trigger.closest("dialog")?.addEventListener("close", hide);

    return { show, hide, place, get isOpen() { return isOpen; } };
}
