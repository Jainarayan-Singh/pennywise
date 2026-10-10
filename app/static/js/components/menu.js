function setupMenu(menu) {
    const trigger = menu.querySelector("[data-menu-trigger]");
    const panel = menu.querySelector("[data-menu-panel]");
    const items = () => [...panel.querySelectorAll('[role="menuitem"]')];

    function setOpen(open, { focus } = {}) {
        panel.hidden = !open;
        trigger.setAttribute("aria-expanded", String(open));
        if (open && focus === "first") items()[0]?.focus();
        if (open && focus === "last") items().at(-1)?.focus();
        if (!open && focus === "trigger") trigger.focus();
    }

    trigger.addEventListener("click", () => setOpen(panel.hidden));
    trigger.addEventListener("keydown", (event) => {
        if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true, { focus: "first" });
        } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true, { focus: "last" });
        }
    });

    panel.addEventListener("keydown", (event) => {
        const list = items();
        const index = list.indexOf(document.activeElement);
        const move = (target) => {
            event.preventDefault();
            target?.focus();
        };
        switch (event.key) {
            case "ArrowDown": move(list[(index + 1) % list.length]); break;
            case "ArrowUp": move(list[(index - 1 + list.length) % list.length]); break;
            case "Home": move(list[0]); break;
            case "End": move(list.at(-1)); break;
            case "Escape": event.preventDefault(); setOpen(false, { focus: "trigger" }); break;
            case "Tab": setOpen(false); break;
            default: break;
        }
    });

    panel.addEventListener("click", (event) => {
        if (event.target.closest('[role="menuitem"]')) setOpen(false, { focus: "trigger" });
    });

    document.addEventListener("click", (event) => {
        if (!panel.hidden && !menu.contains(event.target)) setOpen(false);
    });
}

export function initMenus() {
    for (const menu of document.querySelectorAll("[data-menu]")) setupMenu(menu);
}
