import { icon } from "./icon.js";

const ICONS = { success: "check-circle", error: "alert-circle", warning: "alert-triangle", info: "info" };
const DURATION_MS = { success: 4000, info: 5000, warning: 7000, error: 8000 };
const MAX_VISIBLE = 4;

const active = new Map();

function dismiss(entry) {
    clearTimeout(entry.timer);
    active.delete(entry.key);
    entry.element.remove();
}

function schedule(entry) {
    clearTimeout(entry.timer);
    entry.timer = setTimeout(() => dismiss(entry), DURATION_MS[entry.kind]);
}

function show(kind, message) {
    const key = `${kind}:${message}`;
    const existing = active.get(key);
    if (existing) {
        schedule(existing); // identical message already visible: extend it instead of stacking a duplicate
        return;
    }

    const region = document.getElementById("toast-region");
    const element = document.createElement("div");
    element.className = `toast toast--${kind}`;
    element.setAttribute("role", kind === "error" ? "alert" : "status");

    const text = document.createElement("p");
    text.className = "toast__message";
    text.textContent = message;

    const close = document.createElement("button");
    close.type = "button";
    close.className = "btn btn--ghost btn--icon btn--sm";
    close.setAttribute("aria-label", "Dismiss notification");
    close.append(icon("x"));

    element.append(icon(ICONS[kind], "toast__icon"), text, close);
    const entry = { key, kind, element, timer: null };
    close.addEventListener("click", () => dismiss(entry));
    element.addEventListener("mouseenter", () => clearTimeout(entry.timer));
    element.addEventListener("mouseleave", () => schedule(entry));
    element.addEventListener("focusin", () => clearTimeout(entry.timer));
    element.addEventListener("focusout", () => schedule(entry));

    region.append(element);
    active.set(key, entry);
    schedule(entry);

    while (active.size > MAX_VISIBLE) dismiss(active.values().next().value);
}

export const toast = {
    success: (message) => show("success", message),
    error: (message) => show("error", message),
    warning: (message) => show("warning", message),
    info: (message) => show("info", message),
};
