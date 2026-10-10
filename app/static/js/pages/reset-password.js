import { postJson } from "../services/api-client.js";
import { clearFieldErrors, setAlert, setBusy, showFieldErrors } from "../components/form-helpers.js";
import { toast } from "../components/toast.js";

const form = document.getElementById("reset-form");
const alertBox = document.getElementById("auth-alert");
const token = new URLSearchParams(window.location.search).get("token");
const setup = document.getElementById("main-content").dataset.mode === "setup";

// The link is single-use and the token is not needed in the address bar after this point.
if (token) window.history.replaceState(null, "", window.location.pathname);

if (!token) {
    form.hidden = true;
    setAlert(alertBox, "This link is missing its token. Request a new one from the sign-in page.");
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearFieldErrors(form);
    setAlert(alertBox, "");
    const values = new FormData(form);
    setBusy(form, true);
    try {
        await postJson("/api/v1/auth/password/reset", {
            token, new_password: values.get("new_password"), confirm_password: values.get("confirm_password"),
        });
        form.hidden = true;
        document.getElementById("back-to-login").hidden = false;
        toast.success(setup ? "Your account is ready. You can now sign in." : "Password updated. You can now sign in.");
    } catch (error) {
        if (error.details) showFieldErrors(form, error.details);
        setAlert(alertBox, error.details ? "Please correct the highlighted field." : error.message);
    } finally {
        setBusy(form, false);
    }
});
