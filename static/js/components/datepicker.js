import { enhanceSelect, setSelectValue } from "./dropdown.js";
import { icon } from "./icon.js";
import { createPopup } from "./popup.js";

// Dates are handled as ISO "YYYY-MM-DD" strings and integer parts, never as local-time Date objects,
// so a user's timezone can never shift a day. "Today" comes from the server (the user's own timezone).

const pad = (number) => String(number).padStart(2, "0");
const toIso = (year, month, day) => `${year}-${pad(month)}-${pad(day)}`;

function parseIso(iso) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
    return match ? { year: +match[1], month: +match[2], day: +match[3] } : null;
}

const fromUtc = (time) => toIso(time.getUTCFullYear(), time.getUTCMonth() + 1, time.getUTCDate());
const utc = (iso) => { const { year, month, day } = parseIso(iso); return new Date(Date.UTC(year, month - 1, day)); };
const addDays = (iso, days) => { const { year, month, day } = parseIso(iso); return fromUtc(new Date(Date.UTC(year, month - 1, day + days))); };
const weekdayOf = (iso) => utc(iso).getUTCDay();
const daysInMonth = (year, month) => new Date(Date.UTC(year, month, 0)).getUTCDate();

function addMonths(iso, months) {
    const { year, month, day } = parseIso(iso);
    const target = new Date(Date.UTC(year, month - 1 + months, 1));
    const y = target.getUTCFullYear();
    const m = target.getUTCMonth() + 1;
    return toIso(y, m, Math.min(day, daysInMonth(y, m)));
}

function firstDayOfWeek(locale) {
    try {
        const info = new Intl.Locale(locale);
        const firstDay = info.getWeekInfo?.().firstDay ?? info.weekInfo?.firstDay ?? 1;
        return firstDay % 7; // CLDR uses 1-7 with 7 = Sunday; JS getUTCDay uses 0 = Sunday
    } catch {
        return 1;
    }
}

function element(tag, className, attributes = {}) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
}

class DatePicker {
    constructor(root) {
        this.root = root;
        this.input = root.querySelector('input[type="hidden"]');
        this.trigger = root.querySelector(".datepicker__trigger");
        this.valueText = root.querySelector(".datepicker__value");
        this.clearButton = root.querySelector(".datepicker__clear");

        const { min, max, today, locale, placeholder } = root.dataset;
        this.min = parseIso(min) ? min : null;
        this.max = parseIso(max) ? max : null;
        this.today = parseIso(today) ? today : fromUtc(new Date());
        this.locale = locale || undefined;
        this.placeholder = placeholder || "Select a date";
        this.weekStart = firstDayOfWeek(this.locale);
        this.formatShort = new Intl.DateTimeFormat(this.locale, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
        this.formatLong = new Intl.DateTimeFormat(this.locale, { day: "numeric", month: "long", year: "numeric", weekday: "long", timeZone: "UTC" });
        this.view = { year: 0, month: 0 };
        this.focused = this.today;

        this.buildPanel();
        this.popup = createPopup({ trigger: this.trigger, panel: this.panel, preferredHeight: 420, onDismiss: () => this.close() });
        this.wireEvents();

        this.input.datepicker = this;
        this.input.control = this.trigger;
        this.sync();
    }

    buildPanel() {
        const monthNames = new Intl.DateTimeFormat(this.locale, { month: "long", timeZone: "UTC" });
        this.monthSelect = element("select", "", { "aria-label": "Month" });
        for (let month = 1; month <= 12; month += 1) {
            const option = element("option", "", { value: String(month) });
            option.textContent = monthNames.format(new Date(Date.UTC(2023, month - 1, 1)));
            this.monthSelect.append(option);
        }
        this.yearSelect = element("select", "", { "aria-label": "Year" });
        const minYear = this.min ? parseIso(this.min).year : parseIso(this.today).year - 30;
        const maxYear = this.max ? parseIso(this.max).year : parseIso(this.today).year + 5;
        for (let year = maxYear; year >= minYear; year -= 1) {
            const option = element("option", "", { value: String(year) });
            option.textContent = String(year);
            this.yearSelect.append(option);
        }

        this.previous = element("button", "btn btn--ghost btn--icon btn--sm", { type: "button", "aria-label": "Previous month" });
        this.previous.append(icon("chevron", "datepicker__previous"));
        this.next = element("button", "btn btn--ghost btn--icon btn--sm", { type: "button", "aria-label": "Next month" });
        this.next.append(icon("chevron", "datepicker__next"));

        const header = element("div", "datepicker__header");
        header.append(this.previous, this.monthSelect, this.yearSelect, this.next);

        const weekdayNames = new Intl.DateTimeFormat(this.locale, { weekday: "short", timeZone: "UTC" });
        const headRow = element("tr");
        for (let i = 0; i < 7; i += 1) {
            const dayIndex = (this.weekStart + i) % 7;
            const cell = element("th", "", { scope: "col" });
            cell.textContent = weekdayNames.format(new Date(Date.UTC(2023, 0, 1 + dayIndex)));
            headRow.append(cell);
        }
        this.body = element("tbody");
        this.table = element("table", "calendar", { role: "grid" });
        this.table.append(element("thead"), this.body);
        this.table.tHead.append(headRow);

        this.todayButton = element("button", "btn btn--ghost btn--sm", { type: "button" });
        this.todayButton.textContent = "Today";
        this.footerClear = element("button", "btn btn--ghost btn--sm", { type: "button" });
        this.footerClear.textContent = "Clear";
        const footer = element("div", "datepicker__footer");
        footer.append(this.todayButton);
        if (this.root.hasAttribute("data-clearable")) footer.append(this.footerClear);

        // tabindex keeps focus inside the panel when a click lands on something unfocusable, such as a disabled day.
        this.panel = element("div", "datepicker__panel", { popover: "manual", role: "dialog", "aria-label": "Choose a date", tabindex: "-1" });
        this.panel.append(header, this.table, footer);
        this.root.append(this.panel);
        enhanceSelect(this.monthSelect);
        enhanceSelect(this.yearSelect);
    }

    wireEvents() {
        this.trigger.addEventListener("click", () => (this.popup.isOpen ? this.close() : this.open()));
        this.trigger.addEventListener("keydown", (event) => {
            if (event.key === "ArrowDown") { event.preventDefault(); this.open(); }
        });
        const label = document.querySelector(`label[for="${CSS.escape(this.input.id)}"]`);
        if (label) {
            label.id ||= `${this.input.id}-label`;
            this.trigger.setAttribute("aria-labelledby", `${label.id} ${this.valueText.id}`);
            label.addEventListener("click", () => this.trigger.focus());
        }

        this.previous.addEventListener("click", () => this.shiftMonth(-1));
        this.next.addEventListener("click", () => this.shiftMonth(1));
        this.monthSelect.addEventListener("change", () => this.goTo(this.view.year, +this.monthSelect.value));
        this.yearSelect.addEventListener("change", () => this.goTo(+this.yearSelect.value, this.view.month));
        this.body.addEventListener("click", (event) => {
            const day = event.target.closest(".calendar__day");
            if (day && !day.disabled) this.select(day.dataset.date);
        });
        this.table.addEventListener("keydown", (event) => this.onGridKey(event));
        this.panel.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !event.defaultPrevented) {
                event.preventDefault();
                event.stopPropagation(); // close only the calendar, not a dialog around it
                this.close();
            }
        });
        this.panel.addEventListener("focusout", (event) => {
            const next = event.relatedTarget;
            if (next && !this.panel.contains(next) && next !== this.trigger) this.close({ focusTrigger: false });
        });
        this.todayButton.addEventListener("click", () => this.select(this.clamp(this.today)));
        this.footerClear.addEventListener("click", () => this.select(""));
        this.clearButton?.addEventListener("click", () => { this.setValue(""); this.input.dispatchEvent(new Event("change", { bubbles: true })); });

        new MutationObserver(() => this.sync()).observe(this.input, { attributes: true, attributeFilter: ["disabled", "aria-invalid"] });
        this.input.form?.addEventListener("reset", () => setTimeout(() => this.sync()));
    }

    inRange(iso) {
        return (!this.min || iso >= this.min) && (!this.max || iso <= this.max);
    }

    clamp(iso) {
        if (this.min && iso < this.min) return this.min;
        if (this.max && iso > this.max) return this.max;
        return iso;
    }

    get value() {
        return this.input.value;
    }

    setValue(iso) {
        this.input.value = iso && parseIso(iso) && this.inRange(iso) ? iso : "";
        this.sync();
    }

    sync() {
        const iso = this.input.value;
        this.valueText.textContent = parseIso(iso) ? this.formatShort.format(utc(iso)) : this.placeholder;
        this.valueText.classList.toggle("is-placeholder", !parseIso(iso));
        this.trigger.disabled = this.input.disabled;
        if (this.input.getAttribute("aria-invalid") === "true") this.trigger.setAttribute("aria-invalid", "true");
        else this.trigger.removeAttribute("aria-invalid");
        if (this.clearButton) this.clearButton.hidden = !iso || this.input.disabled;
    }

    open() {
        if (this.popup.isOpen || this.input.disabled) return;
        const start = parseIso(this.value) ? this.value : this.clamp(this.today);
        this.focused = start;
        this.view = { year: parseIso(start).year, month: parseIso(start).month };
        this.render();
        this.popup.show();
        this.trigger.setAttribute("aria-expanded", "true");
        this.focusDay();
    }

    close({ focusTrigger = true } = {}) {
        if (!this.popup.isOpen) return;
        this.popup.hide();
        this.trigger.setAttribute("aria-expanded", "false");
        if (focusTrigger) this.trigger.focus({ preventScroll: true });
    }

    select(iso) {
        this.setValue(iso);
        this.close();
        this.input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    goTo(year, month) {
        const clamped = this.clamp(toIso(year, month, Math.min(parseIso(this.focused).day, daysInMonth(year, month))));
        this.focused = clamped;
        this.view = { year: parseIso(clamped).year, month: parseIso(clamped).month };
        this.render();
    }

    shiftMonth(delta) {
        const moved = addMonths(this.focused, delta);
        this.goTo(parseIso(moved).year, parseIso(moved).month);
    }

    focusDay() {
        this.body.querySelector(`[data-date="${this.focused}"]`)?.focus({ preventScroll: true });
    }

    render() {
        const { year, month } = this.view;
        setSelectValue(this.monthSelect, String(month));
        setSelectValue(this.yearSelect, String(year));
        for (const option of this.monthSelect.options) {
            const candidate = toIso(year, +option.value, 1);
            const last = toIso(year, +option.value, daysInMonth(year, +option.value));
            option.disabled = !this.inRange(candidate) && !this.inRange(last);
        }
        this.previous.disabled = !!this.min && addDays(toIso(year, month, 1), -1) < this.min;
        this.next.disabled = !!this.max && addDays(toIso(year, month, daysInMonth(year, month)), 1) > this.max;
        this.todayButton.disabled = !this.inRange(this.today);
        this.table.setAttribute("aria-label", new Intl.DateTimeFormat(this.locale, { month: "long", year: "numeric", timeZone: "UTC" }).format(utc(toIso(year, month, 1))));

        const firstOfMonth = toIso(year, month, 1);
        const lead = (weekdayOf(firstOfMonth) - this.weekStart + 7) % 7;
        let cursor = addDays(firstOfMonth, -lead);
        const rows = [];
        for (let week = 0; week < 6; week += 1) {
            const row = element("tr");
            for (let i = 0; i < 7; i += 1) {
                row.append(this.dayCell(cursor, month));
                cursor = addDays(cursor, 1);
            }
            rows.push(row);
        }
        this.body.replaceChildren(...rows);
    }

    dayCell(iso, viewMonth) {
        const parts = parseIso(iso);
        const selected = iso === this.value;
        const button = element("button", "calendar__day", {
            type: "button", "data-date": iso, tabindex: iso === this.focused ? "0" : "-1",
            "aria-label": this.formatLong.format(utc(iso)), "aria-pressed": String(selected),
        });
        button.textContent = String(parts.day);
        button.disabled = !this.inRange(iso);
        button.classList.toggle("is-outside", parts.month !== viewMonth);
        button.classList.toggle("is-today", iso === this.today);
        button.classList.toggle("is-selected", selected);
        if (iso === this.today) button.setAttribute("aria-current", "date");
        const cell = element("td", "", { role: "gridcell" });
        cell.append(button);
        return cell;
    }

    onGridKey(event) {
        const moves = {
            ArrowLeft: () => addDays(this.focused, -1),
            ArrowRight: () => addDays(this.focused, 1),
            ArrowUp: () => addDays(this.focused, -7),
            ArrowDown: () => addDays(this.focused, 7),
            PageUp: () => addMonths(this.focused, event.shiftKey ? -12 : -1),
            PageDown: () => addMonths(this.focused, event.shiftKey ? 12 : 1),
            Home: () => addDays(this.focused, -((weekdayOf(this.focused) - this.weekStart + 7) % 7)),
            End: () => addDays(this.focused, 6 - ((weekdayOf(this.focused) - this.weekStart + 7) % 7)),
        };
        if (!moves[event.key]) return;
        event.preventDefault();
        const target = this.clamp(moves[event.key]());
        const sameMonth = parseIso(target).year === this.view.year && parseIso(target).month === this.view.month;
        this.focused = target;
        if (!sameMonth) this.view = { year: parseIso(target).year, month: parseIso(target).month };
        this.render();
        this.focusDay();
    }
}

export function initDatePickers(root = document) {
    for (const element of root.querySelectorAll("[data-datepicker]")) {
        if (!element.querySelector('input[type="hidden"]').datepicker) new DatePicker(element);
    }
}

/** Set a date picker's value from code (ISO date or ""). Out-of-range values are ignored. Does not fire `change`. */
export function setDateValue(input, iso) {
    if (input.datepicker) input.datepicker.setValue(iso);
    else input.value = iso;
}
