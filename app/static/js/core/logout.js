import { confirmAction } from "../components/dialog.js";
import { toast } from "../components/toast.js";
import { postJson } from "../services/api-client.js";
import { navigateWithTransition } from "./page-transition.js";

const VARIANTS = {
    single: {
        title: "Sign out?",
        message: "You'll need to sign in again to see your transactions.",
        confirmLabel: "Sign out",
        endpoint: "/api/v1/auth/logout",
        destination: "/",
        progress: "Signing you out…",
    },
    everywhere: {
        title: "Sign out everywhere?",
        message: "Every device signed in to your account, including this one, will be signed out.",
        confirmLabel: "Sign out everywhere",
        endpoint: "/api/v1/auth/logout-all",
        destination: "/login",
        progress: "Signing you out of every device…",
    },
};

/**
 * Ask first, then end the session on the server. The confirm dialog shows its own spinner while the request
 * runs and stays open with the error if it fails (so the user can retry or cancel). Only after the server
 * confirms do we clear client state and show the transition overlay while the page navigates.
 */
export async function signOut(kind = "single") {
    const variant = VARIANTS[kind];
    const done = await confirmAction({
        title: variant.title,
        message: variant.message,
        confirmLabel: variant.confirmLabel,
        tone: "primary",
        action: () => postJson(variant.endpoint),
    });
    if (!done) return;
    try {
        sessionStorage.clear();
    } catch {
        // Storage may be unavailable; the server session is already ended.
    }
    navigateWithTransition(variant.destination, variant.progress, () =>
        toast.warning("You're signed out, but the page didn't reload. Please reload it."));
}
