import { icon } from "./icon.js";

const byId = (id) => document.getElementById(id);

/** Close buttons (`data-dialog-close`) and backdrop clicks (`data-light-dismiss`) for every dialog. */
export function initDialogs() {
    document.addEventListener("click", (event) => {
        const closer = event.target.closest("[data-dialog-close]");
        if (closer) {
            closer.closest("dialog")?.close();
            return;
        }
        const dialog = event.target;
        if (dialog instanceof HTMLDialogElement && dialog.hasAttribute("data-light-dismiss") && !dialog.dataset.busy) {
            dialog.close();
        }
    });
}

function setConfirmBusy(dialog, busy) {
    const accept = byId("confirm-accept");
    byId("confirm-cancel").disabled = busy;
    accept.disabled = busy;
    if (busy) {
        accept.setAttribute("data-loading", "");
        dialog.dataset.busy = "true";
    } else {
        accept.removeAttribute("data-loading");
        delete dialog.dataset.busy;
    }
}

/**
 * Show the shared confirmation dialog. `action` runs when the user confirms; the dialog stays open
 * with a spinner while it runs, shows the error if it throws, and closes when it succeeds.
 * Resolves true only if the action completed.
 */
export function confirmAction({ title, message, confirmLabel = "Confirm", tone = "danger", action }) {
    const dialog = byId("confirm-dialog");
    const form = byId("confirm-form");
    const accept = byId("confirm-accept");
    const cancel = byId("confirm-cancel");
    const errorBox = byId("confirm-error");
    const iconBox = byId("confirm-icon");

    byId("confirm-title").textContent = title;
    byId("confirm-message").textContent = message;
    accept.textContent = confirmLabel;
    accept.className = `btn ${tone === "danger" ? "btn--danger" : "btn--primary"}`;
    iconBox.className = `modal__icon${tone === "danger" ? " modal__icon--danger" : ""}`;
    iconBox.replaceChildren(icon(tone === "danger" ? "alert-triangle" : "info"));
    errorBox.hidden = true;
    setConfirmBusy(dialog, false);

    return new Promise((resolve) => {
        let confirmed = false;

        const onSubmit = async (event) => {
            event.preventDefault();
            if (dialog.dataset.busy) return;
            errorBox.hidden = true;
            setConfirmBusy(dialog, true);
            try {
                await action?.();
                confirmed = true;
                setConfirmBusy(dialog, false);
                dialog.close();
            } catch (error) {
                errorBox.querySelector("span").textContent = error.message || "Something went wrong. Please try again.";
                errorBox.hidden = false;
                setConfirmBusy(dialog, false);
                cancel.focus();
            }
        };
        const onCancelClick = () => dialog.close();
        const onEscape = (event) => {
            if (dialog.dataset.busy) event.preventDefault();
        };
        const onClose = () => {
            form.removeEventListener("submit", onSubmit);
            cancel.removeEventListener("click", onCancelClick);
            dialog.removeEventListener("cancel", onEscape);
            resolve(confirmed);
        };

        form.addEventListener("submit", onSubmit);
        cancel.addEventListener("click", onCancelClick);
        dialog.addEventListener("cancel", onEscape);
        dialog.addEventListener("close", onClose, { once: true });
        dialog.showModal();
        (tone === "danger" ? cancel : accept).focus(); // destructive actions default to the safe choice
    });
}
