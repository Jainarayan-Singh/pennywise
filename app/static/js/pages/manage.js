import { getJson, postJson, requestJson } from "../services/api-client.js";
import { confirmAction } from "../components/dialog.js";
import { clearFieldErrors, formData, setBusy, showFieldErrors } from "../components/form-helpers.js";
import { icon } from "../components/icon.js";
import { showSkeleton, showState } from "../components/state.js";
import { toast } from "../components/toast.js";
import { humanize } from "../utils/format.js";

const renameDialog = document.getElementById("rename-dialog");
const renameForm = document.getElementById("rename-dialog-form");

const lists = {
    categories: {
        region: document.getElementById("category-lists"),
        archivedOnly: document.getElementById("show-archived-categories"),
        noun: "Category",
    },
    accounts: {
        region: document.getElementById("account-list-region"),
        archivedOnly: document.getElementById("show-archived-accounts"),
        noun: "Account",
    },
};

let renameTarget = null;

function actionButton(label, iconName, onClick, itemName = "") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--ghost btn--sm";
    button.setAttribute("aria-label", itemName ? `${label} ${itemName}` : label);
    const text = document.createElement("span");
    text.className = "btn__label";
    text.textContent = label;
    button.append(icon(iconName), text);
    button.addEventListener("click", () => onClick(button));
    return button;
}

function row(item, collection, detail) {
    const li = document.createElement("li");
    li.className = "list-row";

    const main = document.createElement("div");
    main.className = "list-row__main";
    const title = document.createElement("div");
    title.className = "list-row__title";
    const name = document.createElement("span");
    name.textContent = item.name;
    title.append(name);
    main.append(title);
    if (detail) {
        const sub = document.createElement("span");
        sub.className = "muted small";
        sub.textContent = detail;
        main.append(sub);
    }

    const actions = document.createElement("div");
    actions.className = "btn-group";
    actions.append(actionButton("Rename", "pencil", () => openRename(collection, item), item.name));
    actions.append(item.is_archived
        ? actionButton("Restore", "refresh", (button) => restore(collection, item, button), item.name)
        : actionButton("Archive", "inbox", () => archive(collection, item), item.name));
    li.append(main, actions);
    return li;
}

function renderCategories(region, categories, archivedOnly) {
    if (archivedOnly && categories.length === 0) {
        return showState(region, { iconName: "inbox", title: "No archived categories", text: "Categories you archive will appear here, ready to restore." });
    }
    const groups = [];
    for (const kind of ["expense", "income"]) {
        const items = categories.filter((c) => c.kind === kind);
        if (archivedOnly && items.length === 0) continue;
        const heading = document.createElement("h3");
        heading.className = "subheading";
        heading.textContent = `${humanize(kind)} categories`;
        const list = document.createElement("ul");
        list.className = "list";
        list.append(...items.map((c) => row(c, "categories")));
        groups.push(heading, list);
    }
    region.replaceChildren(...groups);
}

function renderAccounts(region, accounts, archivedOnly) {
    if (accounts.length === 0) {
        return showState(region, archivedOnly
            ? { iconName: "inbox", title: "No archived accounts", text: "Accounts you archive will appear here, ready to restore." }
            : { iconName: "inbox", title: "No accounts yet", text: "Accounts are optional. Add one to record where your money lives." });
    }
    const list = document.createElement("ul");
    list.className = "list";
    list.append(...accounts.map((a) => row(a, "accounts", `${humanize(a.account_type)} · ${a.currency}`)));
    region.replaceChildren(list);
}

const renderers = { categories: renderCategories, accounts: renderAccounts };
const requestCounter = { categories: 0, accounts: 0 };
const firstLoadDone = { categories: false, accounts: false };

/** Reload one list. The skeleton only appears on the very first load, so toggling never flashes. */
async function load(collection) {
    const { region, archivedOnly } = lists[collection];
    const ticket = ++requestCounter[collection];
    if (!firstLoadDone[collection]) showSkeleton(region, collection === "categories" ? 5 : 2);
    try {
        const query = archivedOnly.checked ? "?archived=only" : "";
        const data = await getJson(`/api/v1/${collection}${query}`);
        if (ticket !== requestCounter[collection]) return; // a newer request superseded this one
        renderers[collection](region, data[collection], archivedOnly.checked);
        firstLoadDone[collection] = true;
    } catch (error) {
        if (ticket !== requestCounter[collection]) return;
        showState(region, {
            kind: "error", iconName: "alert-circle", title: "Couldn't load this list",
            text: error.message, actionLabel: "Try again", onAction: () => load(collection),
        });
    }
}

async function setArchived(collection, item, archived) {
    await requestJson("PATCH", `/api/v1/${collection}/${item.id}`, { body: { is_archived: archived } });
    await load(collection);
}

async function archive(collection, item) {
    const noun = lists[collection].noun.toLowerCase();
    const archived = await confirmAction({
        title: `Archive “${item.name}”?`,
        message: `It will be hidden from your lists and from new transactions. Past transactions keep it, and you can restore this ${noun} any time using “Archived only”.`,
        confirmLabel: "Archive",
        tone: "primary",
        action: () => setArchived(collection, item, true),
    });
    if (archived) toast.success(`${lists[collection].noun} archived.`);
}

async function restore(collection, item, button) {
    button.disabled = true;
    try {
        await setArchived(collection, item, false);
        toast.success(`${lists[collection].noun} restored.`);
    } catch (error) {
        toast.error(error.message);
        button.disabled = false;
    }
}

function openRename(collection, item) {
    renameTarget = { collection, item };
    document.getElementById("rename-dialog-title").textContent = `Rename “${item.name}”`;
    clearFieldErrors(renameForm);
    renameForm.elements.name.value = item.name;
    renameDialog.showModal();
    renameForm.elements.name.select();
}

renameForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearFieldErrors(renameForm);
    const name = renameForm.elements.name.value;
    setBusy(renameForm, true);
    try {
        await requestJson("PATCH", `/api/v1/${renameTarget.collection}/${renameTarget.item.id}`, { body: { name } });
        renameDialog.close();
        toast.success("Renamed.");
        await load(renameTarget.collection);
    } catch (error) {
        if (error.details) showFieldErrors(renameForm, error.details);
        else toast.error(error.message);
    } finally {
        setBusy(renameForm, false);
    }
});

function wireCreateForm(formId, collection) {
    const form = document.getElementById(formId);
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        clearFieldErrors(form);
        const body = formData(form);
        setBusy(form, true);
        try {
            await postJson(`/api/v1/${collection}`, body);
            form.reset();
            toast.success(`${lists[collection].noun} added.`);
            if (!lists[collection].archivedOnly.checked) await load(collection);
        } catch (error) {
            if (error.details) showFieldErrors(form, error.details);
            else toast.error(error.message);
        } finally {
            setBusy(form, false);
        }
    });
}

wireCreateForm("category-form", "categories");
wireCreateForm("account-form", "accounts");
for (const collection of Object.keys(lists)) {
    lists[collection].archivedOnly.addEventListener("change", () => load(collection));
    load(collection);
}
