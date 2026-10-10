import { countUp, hideTip, renderBars, renderDonut, renderTrend } from "../components/charts.js";
import { setSelectValue } from "../components/dropdown.js";
import { icon } from "../components/icon.js";
import { showSkeleton, showState } from "../components/state.js";
import { getJson } from "../services/api-client.js";
import { formatDate, formatMoney, humanize } from "../utils/format.js";

const main = document.getElementById("main-content");
const { locale } = main.dataset;
const els = {
    intro: document.getElementById("dashboard-intro"),
    content: document.getElementById("dashboard-content"),
    empty: document.getElementById("dashboard-empty"),
    stats: document.getElementById("dashboard-stats"),
    range: document.getElementById("dashboard-range"),
    currency: document.getElementById("dashboard-currency"),
    currencyField: document.getElementById("dashboard-currency-field"),
    bars: document.getElementById("chart-bars"),
    donut: document.getElementById("chart-donut"),
    donutSub: document.getElementById("donut-sub"),
    trend: document.getElementById("chart-trend"),
    trendSub: document.getElementById("trend-sub"),
    recent: document.getElementById("recent-list"),
};

const TILES = [
    { key: "balance", label: "Total balance", iconName: "wallet" },
    { key: "income", label: "Income", iconName: "arrow-down" },
    { key: "expense", label: "Expenses", iconName: "arrow-up" },
    { key: "savings", label: "Savings", iconName: "trend-up" },
];

const state = { range: "this_month", currency: main.dataset.currency, data: null, request: 0 };
const tiles = new Map();
const shown = new Map(); // last figure on each tile, so the next update counts from it

const money = (amount, currency = state.data?.currency) => formatMoney(amount, currency, locale);

// ---------- summary tiles ----------

function buildTiles() {
    els.stats.replaceChildren();
    TILES.forEach(({ key, label, iconName }, index) => {
        const tile = document.createElement("article");
        tile.className = `card stat-tile stat-tile--${key}`;
        tile.style.setProperty("--i", index);
        const head = document.createElement("div");
        head.className = "stat-tile__head";
        const chip = document.createElement("span");
        chip.className = "stat-tile__icon";
        chip.append(icon(iconName));
        const title = document.createElement("h2");
        title.className = "stat-tile__label";
        title.textContent = label;
        head.append(chip, title);
        const value = document.createElement("p");
        value.className = "stat-tile__value numeric";
        const note = document.createElement("p");
        note.className = "stat-tile__note";
        tile.append(head, value, note);
        els.stats.append(tile);
        tiles.set(key, { value, note });
    });
}

function changeNote(change, goodWhenUp) {
    if (change === null) return { text: "No earlier period to compare with", tone: "" };
    const amount = Number(change);
    if (amount === 0) return { text: "Same as the previous period", tone: "" };
    const text = `${amount > 0 ? "▲" : "▼"} ${Math.abs(amount)}% vs previous period`;
    return { text, tone: (amount > 0) === goodWhenUp ? "is-good" : "is-bad" };
}

function tileNote(key, summary) {
    if (key === "balance") return { text: "All income minus all spending so far", tone: "" };
    if (key === "income") return changeNote(summary.income_change, true);
    if (key === "expense") return changeNote(summary.expense_change, false);
    if (summary.savings_rate === null) return { text: "No income recorded in this period", tone: "" };
    if (Number(summary.savings) < 0) return { text: "You spent more than you earned", tone: "is-bad" };
    return { text: `You kept ${summary.savings_rate}% of your income`, tone: "is-good" };
}

function renderTiles(data) {
    if (tiles.size === 0) buildTiles();
    const { summary } = data;
    const amounts = { balance: summary.balance, income: summary.income, expense: summary.expense, savings: summary.savings };
    for (const { key } of TILES) {
        const tile = tiles.get(key);
        countUp(tile.value, amounts[key], { currency: data.currency, locale, from: shown.get(key) ?? 0 });
        tile.value.classList.toggle("is-negative", Number(amounts[key]) < 0);
        shown.set(key, Number(amounts[key]));
        const { text, tone } = tileNote(key, summary);
        tile.note.textContent = text;
        tile.note.className = `stat-tile__note ${tone}`;
    }
}

// ---------- charts ----------

function renderCharts(animate) {
    const { data } = state;
    if (!data) return;
    const { currency, summary } = data;
    const hasAnyMonth = data.months.some((month) => Number(month.income) > 0 || Number(month.expense) > 0);

    if (hasAnyMonth) {
        renderBars(els.bars, { months: data.months, currency, locale, animate });
    } else {
        showState(els.bars, { iconName: "inbox", title: "No money moved yet", text: "Income and expenses will show up here, month by month." });
    }

    if (data.categories.length > 0) {
        renderDonut(els.donut, { categories: data.categories, total: summary.expense, currency, locale });
    } else {
        showState(els.donut, { iconName: "inbox", title: "No spending in this period", text: "Pick a longer period, or add an expense to see where your money goes." });
    }

    els.trendSub.textContent = data.trend.granularity === "week" ? "How much you spent each week." : "How much you spent each day.";
    if (Number(summary.expense) > 0) {
        renderTrend(els.trend, { points: data.trend.points, granularity: data.trend.granularity, currency, locale, animate });
    } else {
        showState(els.trend, { iconName: "inbox", title: "No spending in this period", text: "Your daily spending will be drawn here." });
    }
}

// Redraw at the new width when a chart's container resizes (no entrance animation, so it never replays).
const widths = new WeakMap();
const observer = new ResizeObserver((entries) => {
    let changed = false;
    for (const { target, contentRect } of entries) {
        const width = Math.round(contentRect.width);
        if (widths.has(target) && widths.get(target) !== width) changed = true;
        widths.set(target, width);
    }
    if (changed) renderCharts(false);
});
observer.observe(els.bars);
observer.observe(els.trend);

// ---------- recent transactions ----------

function renderRecent(items) {
    if (items.length === 0) {
        showState(els.recent, { iconName: "inbox", title: "Nothing here yet", text: "Your latest transactions will appear here." });
        return;
    }
    const list = document.createElement("ul");
    list.className = "activity";
    for (const item of items) {
        const row = document.createElement("li");
        const text = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = item.merchant || item.description || humanize(item.type);
        const meta = document.createElement("span");
        meta.className = "muted small";
        meta.textContent = `${formatDate(item.transaction_date, locale)} · ${item.category?.name ?? "Uncategorised"}`;
        text.append(title, meta);
        const amount = document.createElement("span");
        amount.className = `numeric ${item.type === "income" ? "amount--income" : "amount--expense"}`;
        amount.textContent = `${item.type === "income" ? "+" : "−"}${money(item.amount, item.currency)}`;
        row.append(text, amount);
        list.append(row);
    }
    els.recent.replaceChildren(list);
}

// ---------- page ----------

function syncFilters(data) {
    setSelectValue(els.range, data.range.key);
    els.currencyField.hidden = data.currencies.length < 2;
    if (data.currencies.length >= 2) {
        els.currency.replaceChildren(...data.currencies.map((code) => new Option(code, code)));
        setSelectValue(els.currency, data.currency);
    }
}

function render(data) {
    state.data = data;
    state.range = data.range.key;
    state.currency = data.currency;
    if (!data.has_transactions) {
        els.content.hidden = true;
        els.empty.hidden = false;
        els.empty.className = "card";
        showState(els.empty, {
            iconName: "inbox",
            title: "Add your first transaction",
            text: "Record an income or expense and your dashboard will fill in with totals, charts and your biggest spending categories.",
            actionLabel: "Add transaction",
            onAction: () => window.location.assign("/transactions?new=1"),
        });
        return;
    }
    els.empty.hidden = true;
    els.content.hidden = false;
    els.intro.textContent = `${data.range.label} (${formatDate(data.range.start, locale)} to ${formatDate(data.range.end, locale)}), in ${data.currency}.`;
    syncFilters(data);
    renderTiles(data);
    renderCharts(true);
    renderRecent(data.recent);
}

async function load({ first = false } = {}) {
    const request = ++state.request;
    hideTip();
    if (first) {
        showSkeleton(els.stats, 3);
        for (const host of [els.bars, els.donut, els.trend, els.recent]) showSkeleton(host, 4);
    }
    try {
        const params = new URLSearchParams({ range: state.range, currency: state.currency });
        const data = await getJson(`/api/v1/dashboard?${params}`);
        if (request === state.request) {
            if (first) tiles.clear();
            render(data);
        }
    } catch (error) {
        if (request !== state.request) return;
        els.content.hidden = true;
        els.empty.hidden = false;
        els.empty.className = "card";
        showState(els.empty, {
            kind: "error", iconName: "alert-circle", title: "Couldn't load your dashboard",
            text: error.message, actionLabel: "Try again", onAction: () => { els.content.hidden = false; els.empty.hidden = true; load({ first: true }); },
        });
    }
}

els.range.addEventListener("change", () => { state.range = els.range.value; load(); });
els.currency.addEventListener("change", () => { state.currency = els.currency.value; load(); });

load({ first: true });
