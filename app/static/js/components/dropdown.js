import { icon } from "./icon.js";
import { createPopup } from "./popup.js";

const SEARCH_THRESHOLD = 8;
const TYPEAHEAD_RESET_MS = 700;
const PAGE_STEP = 8;
let nextId = 0;

function element(tag, className, attributes = {}) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
}

/**
 * Accessible custom dropdown layered over a native <select>, which stays the source of truth (form value,
 * `change` events, validation, and the no-JavaScript fallback). Use `setSelectValue` when changing it from code.
 */
class Dropdown {
    constructor(select) {
        this.select = select;
        this.id = select.id || `dropdown-${++nextId}`;
        this.query = "";
        this.visible = [];
        this.activeIndex = -1;
        this.typeahead = { text: "", timer: null };

        this.root = select.closest(".dropdown");
        if (!this.root) {
            this.root = element("div", "dropdown");
            select.before(this.root);
            this.root.append(select);
        }

        this.valueText = element("span", "dropdown__value", { id: `${this.id}-value` });
        this.chevron = icon("chevron", "dropdown__chevron");
        this.trigger = element("button", "input dropdown__trigger", {
            type: "button",
            role: "combobox",
            "aria-haspopup": "listbox",
            "aria-expanded": "false",
            "aria-controls": `${this.id}-list`,
        });
        this.trigger.append(this.valueText, this.chevron);

        this.panel = element("div", "dropdown__panel", { popover: "manual" });
        this.search = element("input", "input dropdown__search", {
            type: "search", role: "combobox", "aria-label": "Search options", "aria-autocomplete": "list",
            "aria-controls": `${this.id}-list`, autocomplete: "off", placeholder: "Search…",
        });
        this.list = element("ul", "dropdown__list", { id: `${this.id}-list`, role: "listbox", tabindex: "-1" });
        this.panel.append(this.search, this.list);
        this.root.append(this.trigger, this.panel);

        this.popup = createPopup({ trigger: this.trigger, panel: this.panel, onDismiss: () => this.close() });
        this.wireAccessibility();
        this.wireEvents();

        select.hidden = true;
        select.tabIndex = -1;
        select.dropdown = this;
        select.control = this.trigger;
        this.sync();
    }

    wireAccessibility() {
        const label = document.querySelector(`label[for="${CSS.escape(this.select.id)}"]`);
        if (label) {
            label.id ||= `${this.id}-label`;
            this.trigger.setAttribute("aria-labelledby", `${label.id} ${this.valueText.id}`);
            this.list.setAttribute("aria-labelledby", label.id);
            label.addEventListener("click", () => this.trigger.focus());
        }
        const described = this.select.getAttribute("aria-describedby");
        if (described) this.trigger.setAttribute("aria-describedby", described);
    }

    wireEvents() {
        this.trigger.addEventListener("click", () => (this.popup.isOpen ? this.close() : this.open()));
        this.trigger.addEventListener("keydown", (event) => {
            if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
                event.preventDefault();
                this.open();
            }
        });
        this.panel.addEventListener("keydown", (event) => this.onKeydown(event));
        this.list.addEventListener("mousemove", (event) => {
            const index = this.indexOfNode(event.target);
            if (index >= 0 && index !== this.activeIndex) this.setActive(index, { scroll: false });
        });
        this.list.addEventListener("click", (event) => {
            const index = this.indexOfNode(event.target);
            if (index >= 0) this.choose(index);
        });
        this.search.addEventListener("input", () => {
            this.query = this.search.value.trim().toLowerCase();
            this.renderList();
            this.setActive(this.visible.findIndex((item) => !item.option.disabled));
        });

        let queued = false;
        new MutationObserver(() => {
            if (queued) return;
            queued = true;
            queueMicrotask(() => { queued = false; this.sync(); });
        }).observe(this.select, {
            childList: true, subtree: true, attributes: true,
            attributeFilter: ["disabled", "aria-invalid", "data-loading", "selected"],
        });
        this.select.form?.addEventListener("reset", () => setTimeout(() => this.sync()));
    }

    get isSearchable() {
        const setting = this.select.dataset.searchable;
        return setting === "true" || (setting !== "false" && this.select.options.length > SEARCH_THRESHOLD);
    }

    /** Refresh the trigger (value, disabled, invalid, loading) and, if open, the option list. */
    sync() {
        const selected = this.select.selectedOptions[0];
        const isPlaceholder = !selected || selected.value === "";
        this.valueText.textContent = selected?.textContent.trim() || "Select…";
        this.valueText.classList.toggle("is-placeholder", isPlaceholder);
        this.trigger.title = selected?.textContent.trim() ?? "";
        this.trigger.disabled = this.select.disabled;
        if (this.select.getAttribute("aria-invalid") === "true") this.trigger.setAttribute("aria-invalid", "true");
        else this.trigger.removeAttribute("aria-invalid");
        this.trigger.setAttribute("aria-busy", String(this.select.hasAttribute("data-loading")));
        if (this.popup.isOpen) this.renderList();
    }

    renderList() {
        const loading = this.select.hasAttribute("data-loading");
        this.list.replaceChildren();
        this.visible = [];
        if (loading) return this.showMessage("Loading…", true);

        let group = null;
        for (const node of this.select.children) {
            if (node instanceof HTMLOptGroupElement) {
                const matches = [...node.children].filter((option) => this.matches(option));
                if (matches.length === 0) continue;
                group = element("li", "dropdown__group", { role: "presentation" });
                group.textContent = node.label;
                this.list.append(group);
                matches.forEach((option) => this.addOption(option));
            } else if (this.matches(node)) {
                this.addOption(node);
            }
        }
        const realOptions = [...this.select.options].filter((option) => option.value !== "");
        if (realOptions.length === 0 && this.visible.length <= 1) this.showMessage("No options available");
        else if (this.visible.length === 0) this.showMessage("No matches");
    }

    matches(option) {
        return !this.query || option.textContent.toLowerCase().includes(this.query);
    }

    addOption(option) {
        const node = element("li", "dropdown__option", {
            role: "option", id: `${this.id}-option-${this.visible.length}`,
            "aria-selected": String(option.selected),
        });
        if (option.disabled) node.setAttribute("aria-disabled", "true");
        if (option.value === "") node.classList.add("is-placeholder");
        node.textContent = option.textContent.trim();
        this.list.append(node);
        this.visible.push({ option, node });
    }

    showMessage(text, spinner = false) {
        const row = element("li", "dropdown__message", { role: "presentation" });
        if (spinner) row.append(element("span", "spinner", { "aria-hidden": "true" }));
        row.append(text);
        this.list.append(row);
    }

    indexOfNode(target) {
        const node = target.closest?.(".dropdown__option");
        return this.visible.findIndex((item) => item.node === node);
    }

    open() {
        if (this.popup.isOpen || this.select.disabled) return;
        this.query = "";
        this.search.value = "";
        this.search.hidden = !this.isSearchable;
        this.renderList();
        this.popup.show();
        this.trigger.setAttribute("aria-expanded", "true");
        const selectedIndex = this.visible.findIndex((item) => item.option.selected);
        this.setActive(selectedIndex >= 0 ? selectedIndex : this.visible.findIndex((item) => !item.option.disabled));
        (this.isSearchable ? this.search : this.list).focus({ preventScroll: true });
    }

    close({ focusTrigger = true } = {}) {
        if (!this.popup.isOpen) return;
        this.popup.hide();
        this.trigger.setAttribute("aria-expanded", "false");
        if (focusTrigger) this.trigger.focus({ preventScroll: true });
    }

    setActive(index, { scroll = true } = {}) {
        this.activeIndex = index;
        for (const [position, item] of this.visible.entries()) item.node.classList.toggle("is-active", position === index);
        const active = this.visible[index]?.node;
        const owner = this.isSearchable ? this.search : this.list;
        if (active) owner.setAttribute("aria-activedescendant", active.id);
        else owner.removeAttribute("aria-activedescendant");
        if (active && scroll) active.scrollIntoView({ block: "nearest" });
    }

    move(step) {
        if (this.visible.length === 0) return;
        let index = this.activeIndex;
        for (let tries = 0; tries < this.visible.length; tries += 1) {
            index = Math.min(this.visible.length - 1, Math.max(0, index + step));
            if (!this.visible[index].option.disabled) break;
            if (index === 0 || index === this.visible.length - 1) break;
        }
        this.setActive(index);
    }

    choose(index) {
        const item = this.visible[index];
        if (!item || item.option.disabled) return;
        const changed = this.select.selectedIndex !== item.option.index;
        this.select.selectedIndex = item.option.index;
        this.close();
        this.sync();
        if (changed) this.select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    onKeydown(event) {
        const handled = {
            ArrowDown: () => this.move(1),
            ArrowUp: () => this.move(-1),
            PageDown: () => this.move(PAGE_STEP),
            PageUp: () => this.move(-PAGE_STEP),
            Home: () => this.setActive(this.visible.findIndex((item) => !item.option.disabled)),
            End: () => this.setActive(this.visible.length - 1),
            Enter: () => this.choose(this.activeIndex),
            Escape: () => this.close(),
        };
        if (event.key === " " && !this.isSearchable) {
            event.preventDefault();
            this.choose(this.activeIndex);
        } else if (handled[event.key]) {
            event.preventDefault();
            event.stopPropagation(); // Escape must close only the dropdown, not the dialog it sits in
            handled[event.key]();
        } else if (event.key === "Tab") {
            this.close();
        } else if (!this.isSearchable && event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
            this.typeAhead(event.key);
        }
    }

    typeAhead(character) {
        clearTimeout(this.typeahead.timer);
        this.typeahead.text += character.toLowerCase();
        this.typeahead.timer = setTimeout(() => { this.typeahead.text = ""; }, TYPEAHEAD_RESET_MS);
        const start = this.typeahead.text.length === 1 ? this.activeIndex + 1 : this.activeIndex;
        const ordered = [...this.visible.keys()].map((_, i) => (start + i) % this.visible.length);
        const hit = ordered.find((i) => this.visible[i].option.textContent.trim().toLowerCase().startsWith(this.typeahead.text));
        if (hit !== undefined) this.setActive(hit);
    }
}

export function enhanceSelect(select) {
    return select.dropdown ?? new Dropdown(select);
}

export function initDropdowns(root = document) {
    for (const select of root.querySelectorAll("select[data-dropdown]")) enhanceSelect(select);
}

/** Set a dropdown's value from code and refresh its display. Does not fire `change`. */
export function setSelectValue(select, value) {
    select.value = value;
    select.dropdown?.sync();
}
