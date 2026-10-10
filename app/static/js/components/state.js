import { icon } from "./icon.js";

const SKELETON_WIDTHS = ["long", "medium", "short"];

/** Replace a container's content with an empty/error state: icon, title, text and an optional action. */
export function showState(container, { kind = "empty", iconName = "inbox", title, text, actionLabel, onAction }) {
    const wrapper = document.createElement("div");
    wrapper.className = `state${kind === "error" ? " state--error" : ""}`;

    const iconBox = document.createElement("span");
    iconBox.className = "state__icon";
    iconBox.append(icon(iconName));

    const heading = document.createElement("h3");
    heading.textContent = title;
    wrapper.append(iconBox, heading);

    if (text) {
        const paragraph = document.createElement("p");
        paragraph.className = "state__text";
        paragraph.textContent = text;
        wrapper.append(paragraph);
    }
    if (actionLabel) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn--secondary";
        button.textContent = actionLabel;
        button.addEventListener("click", onAction);
        wrapper.append(button);
    }
    container.replaceChildren(wrapper);
}

/** Placeholder lines shown while data loads. */
export function showSkeleton(container, rows = 4) {
    const list = document.createElement("div");
    list.className = "skeleton-list";
    list.setAttribute("aria-hidden", "true");
    for (let i = 0; i < rows; i += 1) {
        const line = document.createElement("div");
        line.className = `skeleton skeleton--line skeleton--${SKELETON_WIDTHS[i % SKELETON_WIDTHS.length]}`;
        list.append(line);
    }
    container.replaceChildren(list);
}

