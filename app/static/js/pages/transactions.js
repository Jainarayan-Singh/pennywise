import { deleteJson, getJson, requestJson } from "../services/api-client.js";
import { setDateValue } from "../components/datepicker.js";
import { confirmAction } from "../components/dialog.js";
import { setSelectValue } from "../components/dropdown.js";
import {
    clearFieldErrors, fillSelect, setAlert, setBusy, showFieldErrors,
} from "../components/form-helpers.js";
import { icon } from "../components/icon.js";
import { showSkeleton, showState } from "../components/state.js";
import { toast } from "../components/toast.js";
import { formatDate, formatMoney, humanize } from "../utils/format.js";

const PER_PAGE = 20;
const { today, currency: defaultCurrency, locale } = document.getElementById("main-content").dataset;

const els = {
    summary: document.getElementById("summary-cards"),
    filterForm: document.getElementById("filter-form"),
    range: document.getElementById("filter-range"),
    customRange: document.querySelectorAll("[data-custom-range]"),
    listState: document.getElementById("list-state"),
    tableWrap: document.getElementById("table-wrap"),
    rows: document.getElementById("transaction-rows"),
    pagination: document.getElementById("pagination"),
    pageStatus: document.getElementById("page-status"),
    prev: document.getElementById("prev-page-button"),
    next: document.getElementById("next-page-button"),
    dialog: document.getElementById("transaction-dialog"),
    form: document.getElementById("transaction-dialog-form"),
    formTitle: document.getElementById("transaction-dialog-title"),
    formAlert: document.getElementById("transaction-dialog-alert"),
    currencyHint: document.getElementById("tx-currency-hint"),
};

const state = { page: 1, items: [], categories: [], accounts: [], editing: null, idempotencyKey: null };

const money = (amount, currency) => formatMoney(amount, currency, locale);
const labelFor = (item) => item.merchant || item.description || humanize(item.type);

function queryString({ paged }) {
    const params = new URLSearchParams();
    const data = new FormData(els.filterForm);
    const range = data.get("range");
    if (range === "custom") {
        for (const key of ["date_from", "date_to"]) if (data.get(key)) params.set(key, data.get(key));
    } else if (range) {
        params.set("range", range);
    }
    for (const key of ["type", "category_id", "account_id", "q"]) {
        const value = String(data.get(key) ?? "").trim();
        if (value) params.set(key, value);
    }
    if (paged) {
        const [sort, order] = String(data.get("sort")).split(":");
        params.set("sort", sort);
        params.set("order", order);
        params.set("page", String(state.page));
        params.set("per_page", String(PER_PAGE));
    }
    return params.toString();
}

const hasFilters = () => queryString({ paged: false }) !== "";

function categoryOptions(type, keepId = "") {
    return state.categories
        .filter((c) => c.kind === type && (!c.is_archived || c.id === keepId))
        .map((c) => ({ value: c.id, label: c.is_archived ? `${c.name} (archived)` : c.name }));
}

function accountOptions(keepId = "") {
    return state.accounts
        .filter((a) => !a.is_archived || a.id === keepId)
        .map((a) => ({ value: a.id, label: `${a.name} (${a.currency})${a.is_archived ? " (archived)" : ""}` }));
}

function renderSummary(totals) {
    els.summary.replaceChildren(...totals.map((total) => {
        const card = document.createElement("article");
        card.className = "card stat";
        const title = document.createElement("h2");
        title.className = "stat__title";
        title.textContent = `${total.currency} · ${total.count} transaction${total.count === 1 ? "" : "s"}`;
        const rows = document.createElement("dl");
        rows.className = "stat__rows";
        for (const [label, key, cls] of [["Income", "income", "amount--income"], ["Expenses", "expense", "amount--expense"], ["Net", "net", ""]]) {
            const dt = document.createElement("dt");
            dt.textContent = label;
            const dd = document.createElement("dd");
            dd.textContent = money(total[key], total.currency);
            if (cls) dd.className = cls;
            rows.append(dt, dd);
        }
        card.append(title, rows);
        return card;
    }));
}

function cell(label, className, ...children) {
    const td = document.createElement("td");
    td.dataset.label = label;
    if (className) td.className = className;
    td.append(...children);
    return td;
}

function iconButton(label, iconName, className, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `btn btn--sm ${className}`;
    button.append(icon(iconName), label);
    button.addEventListener("click", onClick);
    return button;
}

function renderRows(items) {
    els.rows.replaceChildren(...items.map((item) => {
        const primary = document.createElement("div");
        primary.className = "table__primary";
        const title = document.createElement("strong");
        title.textContent = labelFor(item);
        primary.append(title);
        if (item.merchant && item.description) {
            const sub = document.createElement("span");
            sub.className = "muted";
            sub.textContent = item.description;
            primary.append(sub);
        }

        const amount = document.createElement("span");
        amount.className = item.type === "income" ? "amount--income" : "amount--expense";
        amount.textContent = `${item.type === "income" ? "+" : "−"}${money(item.amount, item.currency)}`;

        const actions = document.createElement("div");
        actions.className = "btn-group";
        actions.append(
            iconButton("Edit", "pencil", "btn--ghost", () => openDialog(item)),
            iconButton("Delete", "trash", "btn--danger-ghost", () => removeTransaction(item)),
        );

        const tr = document.createElement("tr");
        tr.append(
            cell("Date", "", formatDate(item.transaction_date, locale)),
            cell("Details", "", primary),
            cell("Category", item.category ? "" : "is-empty", item.category ? item.category.name : "—"),
            cell("Account", item.account ? "" : "is-empty", item.account ? item.account.name : "—"),
            cell("Amount", "col-amount", amount),
            cell("", "col-actions", actions),
        );
        return tr;
    }));
}

function renderList(data) {
    state.items = data.items;
    const empty = data.total === 0;
    els.tableWrap.hidden = empty;
    els.pagination.hidden = empty;
    if (empty) {
        showState(els.listState, hasFilters()
            ? { iconName: "filter", title: "No transactions match", text: "Try widening the date range or clearing a filter.", actionLabel: "Clear filters", onAction: resetFilters }
            : { iconName: "inbox", title: "No transactions yet", text: "Record your first income or expense to see it here.", actionLabel: "Add transaction", onAction: () => openDialog() });
        return;
    }
    els.listState.replaceChildren();
    renderRows(data.items);
    els.pageStatus.textContent = `Page ${data.page} of ${data.pages} · ${data.total} transactions`;
    els.prev.disabled = data.page <= 1;
    els.next.disabled = data.page >= data.pages;
}

async function reload() {
    els.tableWrap.hidden = true;
    els.pagination.hidden = true;
    showSkeleton(els.listState, 6);
    try {
        const [list, summary] = await Promise.all([
            getJson(`/api/v1/transactions?${queryString({ paged: true })}`),
            getJson(`/api/v1/transactions/summary?${queryString({ paged: false })}`),
        ]);
        renderList(list);
        renderSummary(summary.totals);
    } catch (error) {
        showState(els.listState, {
            kind: "error", iconName: "alert-circle", title: "Couldn't load transactions",
            text: error.message, actionLabel: "Try again", onAction: reload,
        });
    }
}

async function loadLookups() {
    const [categories, accounts] = await Promise.all([
        getJson("/api/v1/categories?include_archived=true"),
        getJson("/api/v1/accounts?include_archived=true"),
    ]);
    state.categories = categories.categories;
    state.accounts = accounts.accounts;
    fillSelect(
        document.getElementById("filter-category"),
        state.categories.map((c) => ({ value: c.id, label: c.is_archived ? `${c.name} (archived)` : c.name, group: `${humanize(c.kind)} categories` })),
    );
    fillSelect(document.getElementById("filter-account"), state.accounts.map((a) => ({ value: a.id, label: a.name })));
}

const field = (name) => els.form.elements[name];
const selectedType = () => field("type").value;

function refreshCategorySelect() {
    fillSelect(field("category_id"), categoryOptions(selectedType()), { selected: field("category_id").value });
}

function updateCurrencyHint() {
    const account = state.accounts.find((a) => a.id === field("account_id").value);
    els.currencyHint.textContent = account?.currency ?? state.editing?.currency ?? defaultCurrency;
}

/** One modal for both adding and editing; `item` is the transaction being edited, or null to add. */
function openDialog(item = null) {
    state.editing = item;
    state.idempotencyKey = item ? null : crypto.randomUUID();
    clearFieldErrors(els.form);
    setAlert(els.formAlert, "");
    els.form.reset();
    els.formTitle.textContent = item ? "Edit transaction" : "Add transaction";
    field("type").value = item ? item.type : "expense";
    field("amount").value = item ? item.amount : "";
    setDateValue(field("transaction_date"), item ? item.transaction_date : today);
    const categoryId = item?.category?.id ?? "";
    const accountId = item?.account?.id ?? "";
    fillSelect(field("account_id"), accountOptions(accountId), { selected: accountId });
    fillSelect(field("category_id"), categoryOptions(selectedType(), categoryId), { selected: categoryId });
    setSelectValue(field("payment_method"), item?.payment_method ?? "");
    field("merchant").value = item?.merchant ?? "";
    field("description").value = item?.description ?? "";
    field("notes").value = item?.notes ?? "";
    updateCurrencyHint();
    els.dialog.showModal();
    field("amount").focus();
}

function collectBody() {
    const blankToNull = (value) => (value.trim() === "" ? null : value.trim());
    return {
        type: selectedType(),
        amount: field("amount").value.trim(),
        transaction_date: field("transaction_date").value || null,
        category_id: field("category_id").value || null,
        account_id: field("account_id").value || null,
        payment_method: field("payment_method").value || null,
        merchant: blankToNull(field("merchant").value),
        description: blankToNull(field("description").value),
        notes: blankToNull(field("notes").value),
    };
}

async function saveTransaction(event) {
    event.preventDefault();
    clearFieldErrors(els.form);
    setAlert(els.formAlert, "");
    const body = collectBody();
    setBusy(els.form, true);
    try {
        const payload = state.editing
            ? await requestJson("PATCH", `/api/v1/transactions/${state.editing.id}`, { body })
            : await requestJson("POST", "/api/v1/transactions", { body, headers: { "Idempotency-Key": state.idempotencyKey } });
        els.dialog.close();
        if (payload.warnings?.some((w) => w.code === "possible_duplicate")) {
            toast.warning("Saved, but it matches an earlier transaction (same amount, date and merchant). Delete one if it's a mistake.");
        } else {
            toast.success(state.editing ? "Transaction updated." : "Transaction saved.");
        }
        await reload();
    } catch (error) {
        if (error.details) {
            showFieldErrors(els.form, error.details);
            setAlert(els.formAlert, "Please correct the highlighted fields.");
        } else {
            setAlert(els.formAlert, error.message);
        }
    } finally {
        setBusy(els.form, false);
    }
}

async function removeTransaction(item) {
    const deleted = await confirmAction({
        title: "Delete this transaction?",
        message: `“${labelFor(item)}” (${money(item.amount, item.currency)}) will be permanently removed. This can't be undone.`,
        confirmLabel: "Delete transaction",
        action: () => deleteJson(`/api/v1/transactions/${item.id}`),
    });
    if (!deleted) return;
    toast.success("Transaction deleted.");
    if (state.items.length === 1 && state.page > 1) state.page -= 1;
    reload();
}

function resetFilters() {
    els.filterForm.reset();
    for (const customField of els.customRange) customField.hidden = true;
    state.page = 1;
    reload();
}

document.getElementById("add-transaction-button").addEventListener("click", () => openDialog());
els.form.addEventListener("submit", saveTransaction);
for (const radio of els.form.elements.type) radio.addEventListener("change", refreshCategorySelect);
field("account_id").addEventListener("change", updateCurrencyHint);
els.range.addEventListener("change", () => {
    for (const customField of els.customRange) customField.hidden = els.range.value !== "custom";
});
// On phones the filter fields sit behind a button (the attribute has no effect on wider screens).
const filtersToggle = document.getElementById("filters-toggle");
const filterFields = document.getElementById("filter-fields");
function setFiltersOpen(open) {
    filterFields.toggleAttribute("data-collapsed", !open);
    filtersToggle.setAttribute("aria-expanded", String(open));
}
filtersToggle.addEventListener("click", () => setFiltersOpen(filterFields.hasAttribute("data-collapsed")));

els.filterForm.addEventListener("submit", (event) => {
    event.preventDefault();
    state.page = 1;
    setFiltersOpen(false);
    reload();
});
document.getElementById("reset-filters-button").addEventListener("click", resetFilters);
els.prev.addEventListener("click", () => { state.page -= 1; reload(); });
els.next.addEventListener("click", () => { state.page += 1; reload(); });

try {
    await loadLookups();
} catch (error) {
    toast.error(error.message);
}
reload();

// "Add transaction" links elsewhere in the app arrive as /transactions?new=1.
const arrival = new URL(window.location.href);
if (arrival.searchParams.has("new")) {
    arrival.searchParams.delete("new");
    window.history.replaceState(null, "", arrival.pathname + arrival.search);
    openDialog();
}
