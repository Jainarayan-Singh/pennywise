export function formData(form) {
    return Object.fromEntries(new FormData(form).entries());
}

/**
 * Disable a form while it submits. Disabled controls are left out of FormData, so
 * read the values *before* calling this.
 */
export function setBusy(form, busy) {
    for (const control of form.querySelectorAll("button, input, select, textarea")) {
        if (!control.closest("[popover]")) control.disabled = busy; // popups rebuild themselves when reopened
    }
    const submit = form.querySelector('button[type="submit"]');
    if (submit) {
        if (busy) submit.setAttribute("data-loading", "");
        else submit.removeAttribute("data-loading");
    }
    form.setAttribute("aria-busy", String(busy));
}

export function clearFieldErrors(form) {
    for (const slot of form.querySelectorAll("[data-error-for]")) slot.textContent = "";
    for (const input of form.querySelectorAll('[aria-invalid="true"]')) input.removeAttribute("aria-invalid");
}

/** Show per-field messages. Custom controls expose their visible element as `.control` (dropdown, date picker). */
export function showFieldErrors(form, details) {
    let first = null;
    for (const [field, message] of Object.entries(details ?? {})) {
        const slot = form.querySelector(`[data-error-for="${CSS.escape(field)}"]`);
        if (slot) slot.textContent = message;
        const input = form.querySelector(`[name="${CSS.escape(field)}"]`);
        if (input) {
            input.setAttribute("aria-invalid", "true");
            first ??= input.control ?? input;
        }
    }
    first?.focus();
}

/** Show or hide an inline `.alert` (markup: icon + <span>). An empty message hides it. */
export function setAlert(alert, message) {
    alert.querySelector("span").textContent = message;
    alert.hidden = !message;
}

/**
 * Replace a <select>'s options, keeping its first (placeholder) option. Items may carry a `group` name,
 * which becomes an <optgroup>. The dropdown refreshes itself when the options change.
 */
export function fillSelect(select, items, { selected = "" } = {}) {
    const placeholder = select.options[0];
    select.replaceChildren(placeholder);
    const groups = new Map();
    for (const { value, label, group } of items) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        if (!group) {
            select.append(option);
            continue;
        }
        if (!groups.has(group)) {
            const container = document.createElement("optgroup");
            container.label = group;
            groups.set(group, container);
            select.append(container);
        }
        groups.get(group).append(option);
    }
    select.value = items.some((item) => item.value === selected) ? selected : "";
}
