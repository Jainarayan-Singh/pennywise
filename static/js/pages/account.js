import { signOut } from "../core/logout.js";
import { ApiRequestError, deleteJson, getJson } from "../services/api-client.js";
import {
    correctOriginUrl, describePasskeyError, passkeysSupported, registerPasskey, showOriginNotice,
} from "../services/passkey-client.js";
import { confirmAction } from "../components/dialog.js";
import { icon } from "../components/icon.js";
import { showSkeleton, showState } from "../components/state.js";
import { toast } from "../components/toast.js";

const region = document.getElementById("passkey-list-region");
const addButton = document.getElementById("add-passkey-button");
const nicknameInput = document.getElementById("passkey-nickname");

const describe = (error) => (error instanceof ApiRequestError ? error.message : describePasskeyError(error));

function passkeyRow(passkey) {
    const item = document.createElement("li");
    item.className = "list-row";

    const main = document.createElement("div");
    main.className = "list-row__main";
    const title = document.createElement("div");
    title.className = "list-row__title";
    const name = document.createElement("span");
    name.textContent = passkey.nickname;
    title.append(name);
    if (passkey.backed_up) {
        const badge = document.createElement("span");
        badge.className = "badge badge--primary";
        badge.textContent = "Synced";
        title.append(badge);
    }
    const detail = document.createElement("span");
    detail.className = "muted small";
    const used = passkey.last_used_at ? new Date(passkey.last_used_at).toLocaleString() : "never";
    detail.textContent = `Added ${new Date(passkey.created_at).toLocaleDateString()} · last used ${used}`;
    main.append(title, detail);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn btn--danger-ghost btn--sm";
    remove.append(icon("trash"), "Remove");
    remove.addEventListener("click", () => removePasskey(passkey));

    item.append(main, remove);
    return item;
}

function renderPasskeys(passkeys) {
    if (passkeys.length === 0) {
        showState(region, {
            iconName: "key",
            title: "No passkeys yet",
            text: "Add one to sign in with your fingerprint, face or device PIN.",
        });
        return;
    }
    const list = document.createElement("ul");
    list.className = "list";
    list.append(...passkeys.map(passkeyRow));
    region.replaceChildren(list);
}

async function loadPasskeys() {
    showSkeleton(region, 2);
    try {
        renderPasskeys((await getJson("/api/v1/auth/passkeys")).passkeys);
    } catch (error) {
        showState(region, {
            kind: "error", iconName: "alert-circle", title: "Couldn't load your passkeys",
            text: describe(error), actionLabel: "Try again", onAction: loadPasskeys,
        });
    }
}

async function removePasskey(passkey) {
    const removed = await confirmAction({
        title: "Remove this passkey?",
        message: `"${passkey.nickname}" will no longer sign you in. You can add it again whenever you like.`,
        confirmLabel: "Remove passkey",
        action: () => deleteJson(`/api/v1/auth/passkeys/${encodeURIComponent(passkey.id)}`),
    });
    if (removed) {
        toast.success("Passkey removed.");
        loadPasskeys();
    }
}

document.getElementById("logout-all-button").addEventListener("click", () => signOut("everywhere"));

const wrongOrigin = correctOriginUrl();
if (wrongOrigin) {
    showOriginNotice(document.getElementById("passkey-origin-notice"), wrongOrigin);
}
if (wrongOrigin || !passkeysSupported()) {
    addButton.disabled = true;
    nicknameInput.disabled = true;
    if (!wrongOrigin) document.getElementById("passkey-unsupported").hidden = false;
} else {
    addButton.addEventListener("click", async () => {
        addButton.disabled = true;
        addButton.setAttribute("data-loading", "");
        try {
            await registerPasskey(nicknameInput.value);
            nicknameInput.value = "";
            toast.success("Passkey added.");
            await loadPasskeys();
        } catch (error) {
            toast.error(describe(error));
        } finally {
            addButton.disabled = false;
            addButton.removeAttribute("data-loading");
        }
    });
}

loadPasskeys();
