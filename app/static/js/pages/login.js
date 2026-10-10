import { ApiRequestError, postJson } from "../services/api-client.js";
import {
    correctOriginUrl, describePasskeyError, loginWithPasskey, passkeysSupported, showOriginNotice,
} from "../services/passkey-client.js";
import { clearFieldErrors, formData, setAlert, setBusy, showFieldErrors } from "../components/form-helpers.js";
import { toast } from "../components/toast.js";

const alertBox = document.getElementById("auth-alert");
const tabList = document.getElementById("auth-tabs");
const tabs = [...tabList.querySelectorAll('[role="tab"]')];
const forms = {
    login: document.getElementById("login-form"),
    register: document.getElementById("register-form"),
    registerDone: document.getElementById("register-done"),
    forgot: document.getElementById("forgot-form"),
};

const describe = (error) => (error instanceof ApiRequestError ? error.message : describePasskeyError(error));
// The server validated this destination (same-site page only), so it is safe to follow.
const destination = document.getElementById("main-content").dataset.next;
const goToApp = () => window.location.assign(destination);

function showPanel(name, { focus = true } = {}) {
    for (const [key, form] of Object.entries(forms)) form.hidden = key !== name;
    const tabName = name === "registerDone" ? "register" : name;
    for (const tab of tabs) {
        const selected = tab.dataset.panelTarget === tabName;
        tab.setAttribute("aria-selected", String(selected));
        tab.tabIndex = selected ? 0 : -1;
    }
    setAlert(alertBox, "");
    if (focus) forms[name].querySelector("input")?.focus();
}

async function submit(form, url, onSuccess) {
    clearFieldErrors(form);
    setAlert(alertBox, "");
    const body = formData(form);
    setBusy(form, true);
    try {
        onSuccess(await postJson(url, body));
    } catch (error) {
        if (error.details) {
            showFieldErrors(form, error.details);
            setAlert(alertBox, "Please correct the highlighted fields.");
        } else {
            setAlert(alertBox, describe(error));
        }
    } finally {
        setBusy(form, false);
    }
}

for (const trigger of document.querySelectorAll("[data-panel-target]")) {
    trigger.addEventListener("click", () => showPanel(trigger.dataset.panelTarget));
}
tabList.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const index = tabs.indexOf(document.activeElement);
    const next = tabs[(index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    showPanel(next.dataset.panelTarget, { focus: false });
    next.focus();
});

forms.login.addEventListener("submit", (event) => {
    event.preventDefault();
    submit(forms.login, "/api/v1/auth/login", goToApp);
});
forms.register.addEventListener("submit", (event) => {
    event.preventDefault();
    submit(forms.register, "/api/v1/auth/register", () => {
        forms.register.reset();
        showPanel("registerDone", { focus: false });
    });
});
forms.forgot.addEventListener("submit", (event) => {
    event.preventDefault();
    submit(forms.forgot, "/api/v1/auth/password/forgot", () => {
        toast.success("If an account exists for that email, a reset link is on its way.");
        showPanel("login");
    });
});

const passkeySection = document.getElementById("passkey-section");
const passkeyButton = document.getElementById("passkey-login-button");
const wrongOrigin = correctOriginUrl();
if (wrongOrigin) {
    passkeySection.hidden = false;
    passkeyButton.disabled = true;
    showOriginNotice(document.getElementById("passkey-origin-notice"), wrongOrigin);
} else if (passkeysSupported()) {
    passkeySection.hidden = false;
    passkeyButton.addEventListener("click", async () => {
        setAlert(alertBox, "");
        passkeyButton.disabled = true;
        passkeyButton.setAttribute("data-loading", "");
        try {
            await loginWithPasskey();
            goToApp();
        } catch (error) {
            setAlert(alertBox, describe(error));
            passkeyButton.disabled = false;
            passkeyButton.removeAttribute("data-loading");
        }
    });
}

showPanel(new URLSearchParams(window.location.search).get("tab") === "register" ? "register" : "login", { focus: false });
