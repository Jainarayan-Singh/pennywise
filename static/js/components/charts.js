import { formatMoney } from "../utils/format.js";

// Small SVG charts drawn from the numbers the server sends. Geometry uses Number(); every amount shown to the
// user is the server's exact decimal string run through Intl. Bars, lines and slices animate in with CSS.

const SVG_NS = "http://www.w3.org/2000/svg";
const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)");
let chartCount = 0;

function svgNode(name, attributes = {}, className = "") {
    const node = document.createElementNS(SVG_NS, name);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    if (className) node.setAttribute("class", className);
    return node;
}

/** Round the top of the scale up to a tidy number so grid lines land on 1, 2, 2.5 or 5 times a power of ten. */
export function niceScale(maxValue, ticks = 4) {
    const max = maxValue > 0 ? maxValue : 1;
    const rough = max / ticks;
    const magnitude = 10 ** Math.floor(Math.log10(rough));
    const step = [1, 2, 2.5, 5, 10].map((factor) => factor * magnitude).find((candidate) => candidate >= rough);
    return { step, max: step * Math.ceil(max / step) };
}


const tip = document.createElement("div");
tip.className = "chart-tip";
tip.setAttribute("role", "tooltip");
tip.hidden = true;
document.body.append(tip);

function showTip(anchor, title, rows) {
    tip.replaceChildren();
    const heading = document.createElement("strong");
    heading.textContent = title;
    tip.append(heading);
    for (const { label, value, tone } of rows) {
        const row = document.createElement("span");
        row.className = "chart-tip__row";
        if (tone) {
            const swatch = document.createElement("i");
            swatch.className = `swatch swatch--${tone}`;
            row.append(swatch);
        }
        const name = document.createElement("span");
        name.textContent = label;
        const amount = document.createElement("b");
        amount.className = "numeric";
        amount.textContent = value;
        row.append(name, amount);
        tip.append(row);
    }
    tip.hidden = false;
    const box = anchor.getBoundingClientRect();
    const x = Math.min(Math.max(8, box.left + box.width / 2 - tip.offsetWidth / 2), window.innerWidth - tip.offsetWidth - 8);
    const above = box.top - tip.offsetHeight - 10;
    tip.style.setProperty("--tip-x", `${x}px`);
    tip.style.setProperty("--tip-y", `${above >= 8 ? above : box.bottom + 10}px`);
}

export function hideTip() {
    tip.hidden = true;
}

function wireTip(target, title, rows, anchor = target) {
    const show = () => showTip(anchor, title, rows);
    target.addEventListener("pointerenter", show);
    target.addEventListener("focus", show);
    target.addEventListener("pointerleave", hideTip);
    target.addEventListener("blur", hideTip);
}


/** Show `finalAmount` (a decimal string) in `element`, counting up from `from` unless motion is reduced. */
export function countUp(element, finalAmount, { currency, locale, from = 0, duration = 800 }) {
    const exact = formatMoney(finalAmount, currency, locale);
    const target = Number(finalAmount);
    if (REDUCED_MOTION.matches || !Number.isFinite(target) || from === target) {
        element.textContent = exact;
        return;
    }
    const started = performance.now();
    const step = (now) => {
        const progress = Math.min((now - started) / duration, 1);
        const eased = 1 - (1 - progress) ** 3;
        element.textContent = formatMoney((from + (target - from) * eased).toFixed(2), currency, locale);
        if (progress < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
    setTimeout(() => { element.textContent = exact; }, duration + 60); // exact figure even if frames are throttled
}


function drawYAxis(svg, { scale, left, right, top, bottom, locale }) {
    const compact = new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 });
    for (let value = 0; value <= scale.max + scale.step / 2; value += scale.step) {
        const y = bottom - (value / scale.max) * (bottom - top);
        svg.append(svgNode("line", { x1: left, x2: right, y1: y, y2: y }, "chart__grid"));
        const label = svgNode("text", { x: left - 8, y: y + 4, "text-anchor": "end" }, "chart__label");
        label.textContent = compact.format(value);
        svg.append(label);
    }
}

function monthLabel(month, locale, style) {
    const [year, number] = month.split("-").map(Number);
    return new Intl.DateTimeFormat(locale, { month: style, ...(style === "long" ? { year: "numeric" } : {}) })
        .format(new Date(year, number - 1, 1));
}


export function renderBars(container, { months, currency, locale, animate = true }) {
    const width = Math.max(container.clientWidth, 260);
    const compact = width < 480;
    const height = compact ? 230 : 270;
    const margin = { top: 12, right: 8, bottom: 30, left: compact ? 40 : 50 };
    const right = width - margin.right;
    const bottom = height - margin.bottom;
    const money = (amount) => formatMoney(amount, currency, locale);

    const highest = Math.max(...months.flatMap((m) => [Number(m.income), Number(m.expense)]));
    const scale = niceScale(highest);
    const y = (value) => bottom - (value / scale.max) * (bottom - margin.top);

    const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "group", "aria-label": "Income and spending by month" }, "chart");
    if (!animate) svg.classList.add("chart--static");
    drawYAxis(svg, { scale, left: margin.left, right, top: margin.top, bottom, locale });

    const band = (right - margin.left) / months.length;
    const barWidth = Math.min(26, band * 0.34);
    months.forEach((month, index) => {
        const centre = margin.left + band * (index + 0.5);
        const incomeValue = Number(month.income);
        const expenseValue = Number(month.expense);
        const group = svgNode("g", {
            tabindex: 0, role: "img",
            "aria-label": `${monthLabel(month.month, locale, "long")}: income ${money(month.income)}, spent ${money(month.expense)}`,
        }, "chart__group");
        group.style.setProperty("--i", index);
        group.append(svgNode("rect", { x: centre - band / 2, y: margin.top, width: band, height: bottom - margin.top }, "chart__hit"));
        for (const [value, offset, tone] of [[incomeValue, -barWidth - 1.5, "income"], [expenseValue, 1.5, "expense"]]) {
            const barHeight = Math.max(value > 0 ? 2 : 0, bottom - y(value));
            group.append(svgNode("rect", { x: centre + offset, y: bottom - barHeight, width: barWidth, height: barHeight, rx: 4 }, `chart__bar chart__bar--${tone}`));
        }
        const label = svgNode("text", { x: centre, y: height - 8, "text-anchor": "middle" }, "chart__label");
        label.textContent = monthLabel(month.month, locale, "short");
        group.append(label);
        const saved = incomeValue - expenseValue;
        wireTip(group, monthLabel(month.month, locale, "long"), [
            { label: "Income", value: money(month.income), tone: "income" },
            { label: "Spent", value: money(month.expense), tone: "expense" },
            { label: saved >= 0 ? "Saved" : "Overspent", value: money(Math.abs(saved).toFixed(2)), tone: "savings" },
        ]);
        svg.append(group);
    });
    container.replaceChildren(svg);
}


export function renderTrend(container, { points, granularity, currency, locale, animate = true }) {
    const width = Math.max(container.clientWidth, 260);
    const compact = width < 480;
    const height = compact ? 210 : 250;
    const margin = { top: 14, right: 14, bottom: 30, left: compact ? 40 : 50 };
    const right = width - margin.right;
    const bottom = height - margin.bottom;
    const money = (amount) => formatMoney(amount, currency, locale);
    const day = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" });
    const longDay = new Intl.DateTimeFormat(locale, { weekday: "short", day: "numeric", month: "short" });
    const parse = (iso) => { const [yy, mm, dd] = iso.split("-").map(Number); return new Date(yy, mm - 1, dd); };

    const values = points.map((point) => Number(point.amount));
    const scale = niceScale(Math.max(...values));
    const x = (index) => margin.left + (points.length === 1 ? (right - margin.left) / 2 : (index / (points.length - 1)) * (right - margin.left));
    const y = (value) => bottom - (value / scale.max) * (bottom - margin.top);
    const peakIndex = values.indexOf(Math.max(...values));
    const title = (index) => (granularity === "week" ? `Week of ${day.format(parse(points[index].date))}` : longDay.format(parse(points[index].date)));

    chartCount += 1;
    const gradientId = `trend-fill-${chartCount}`;
    const svg = svgNode("svg", {
        viewBox: `0 0 ${width} ${height}`, width, height, tabindex: 0, role: "group",
        "aria-label": `Spending ${granularity === "week" ? "per week" : "per day"}. Highest: ${money(points[peakIndex].amount)} (${title(peakIndex)}). Use the left and right arrow keys to explore.`,
    }, "chart");
    if (!animate) svg.classList.add("chart--static");

    const defs = svgNode("defs");
    const gradient = svgNode("linearGradient", { id: gradientId, x1: 0, y1: 0, x2: 0, y2: 1 });
    gradient.append(svgNode("stop", { offset: "0%", "stop-opacity": 0.35 }, "chart__stop"), svgNode("stop", { offset: "100%", "stop-opacity": 0 }, "chart__stop"));
    defs.append(gradient);
    svg.append(defs);
    drawYAxis(svg, { scale, left: margin.left, right, top: margin.top, bottom, locale });

    const line = points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)} ${y(values[index]).toFixed(1)}`).join(" ");
    svg.append(
        svgNode("path", { d: `${line} L${x(points.length - 1).toFixed(1)} ${bottom} L${x(0).toFixed(1)} ${bottom} Z`, fill: `url(#${gradientId})` }, "chart__area"),
        svgNode("path", { d: line }, "chart__line"),
    );

    const labelCount = Math.min(points.length, compact ? 3 : 5);
    for (let i = 0; i < labelCount; i += 1) {
        const index = labelCount === 1 ? 0 : Math.round((i / (labelCount - 1)) * (points.length - 1));
        const label = svgNode("text", { x: x(index), y: height - 8, "text-anchor": i === 0 && labelCount > 1 ? "start" : i === labelCount - 1 && labelCount > 1 ? "end" : "middle" }, "chart__label");
        label.textContent = day.format(parse(points[index].date));
        svg.append(label);
    }

    const guide = svgNode("line", { y1: margin.top, y2: bottom }, "chart__guide");
    const dot = svgNode("circle", { r: 5 }, "chart__dot");
    guide.setAttribute("visibility", "hidden");
    dot.setAttribute("visibility", "hidden");
    svg.append(guide, dot);

    const activate = (index) => {
        guide.setAttribute("x1", x(index));
        guide.setAttribute("x2", x(index));
        dot.setAttribute("cx", x(index));
        dot.setAttribute("cy", y(values[index]));
        guide.setAttribute("visibility", "visible");
        dot.setAttribute("visibility", "visible");
        showTip(dot, title(index), [{ label: "Spent", value: money(points[index].amount), tone: "expense" }]);
    };
    const clear = () => {
        guide.setAttribute("visibility", "hidden");
        dot.setAttribute("visibility", "hidden");
        hideTip();
    };
    const indexAt = (event) => {
        const box = svg.getBoundingClientRect();
        const ratio = (event.clientX - box.left - margin.left) / (right - margin.left);
        return points.length === 1 ? 0 : Math.min(points.length - 1, Math.max(0, Math.round(ratio * (points.length - 1))));
    };
    let current = peakIndex;
    svg.addEventListener("pointermove", (event) => { current = indexAt(event); activate(current); });
    svg.addEventListener("pointerleave", clear);
    svg.addEventListener("focus", () => activate(current));
    svg.addEventListener("blur", clear);
    svg.addEventListener("keydown", (event) => {
        const move = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
        if (!move) return;
        event.preventDefault();
        current = Math.min(points.length - 1, Math.max(0, current + move));
        activate(current);
    });
    container.replaceChildren(svg);
}


export function renderDonut(container, { categories, total, currency, locale }) {
    const money = (amount) => formatMoney(amount, currency, locale);
    const slices = svgNode("svg", { viewBox: "0 0 120 120", "aria-hidden": "true" }, "donut__svg");
    slices.append(svgNode("circle", { cx: 60, cy: 60, r: 44, pathLength: 100 }, "donut__track"));

    const list = document.createElement("ul");
    list.className = "legend";
    const circles = [];
    let offset = 0;
    categories.forEach((category, index) => {
        const colour = `chart-cat-${Math.min(index + 1, 6)}`;
        const share = Number(category.share);
        const circle = svgNode("circle", {
            cx: 60, cy: 60, r: 44, pathLength: 100, tabindex: 0, role: "img",
            "stroke-dasharray": `${Math.max(share - 0.8, 0.2)} ${100 - Math.max(share - 0.8, 0.2)}`,
            "stroke-dashoffset": -offset,
            "aria-label": `${category.name}: ${money(category.amount)}, ${category.share}% of spending`,
        }, `donut__slice ${colour}`);
        circle.style.setProperty("--i", index);
        offset += share;
        circles.push(circle);
        slices.append(circle);

        const item = document.createElement("li");
        item.className = `legend__item ${colour}`;
        const swatch = document.createElement("i");
        swatch.className = "swatch swatch--cat";
        const name = document.createElement("span");
        name.className = "legend__name";
        name.textContent = category.name;
        const percent = document.createElement("span");
        percent.className = "legend__share numeric";
        percent.textContent = `${category.share}%`;
        const amount = document.createElement("span");
        amount.className = "legend__amount numeric";
        amount.textContent = money(category.amount);
        item.append(swatch, name, percent, amount);
        list.append(item);

        const rows = [{ label: "Spent", value: money(category.amount) }, { label: "Share", value: `${category.share}%` }];
        const highlight = (on) => {
            slices.classList.toggle("donut--active", on);
            circle.classList.toggle("is-hover", on);
            item.classList.toggle("is-hover", on);
        };
        for (const target of [circle, item]) {
            target.addEventListener("pointerenter", () => { highlight(true); showTip(circle, category.name, rows); });
            target.addEventListener("pointerleave", () => { highlight(false); hideTip(); });
        }
        circle.addEventListener("focus", () => { highlight(true); showTip(circle, category.name, rows); });
        circle.addEventListener("blur", () => { highlight(false); hideTip(); });
    });

    const centre = document.createElement("div");
    centre.className = "donut__centre";
    const caption = document.createElement("span");
    caption.textContent = "Total spent";
    const figure = document.createElement("strong");
    figure.className = "numeric";
    figure.textContent = money(total);
    centre.append(caption, figure);

    const wrapper = document.createElement("div");
    wrapper.className = "donut";
    const ring = document.createElement("div");
    ring.className = "donut__ring";
    ring.append(slices, centre);
    wrapper.append(ring, list);
    container.replaceChildren(wrapper);
}
