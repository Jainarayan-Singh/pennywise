const SVG_NS = "http://www.w3.org/2000/svg";

/** Reference a symbol from the sprite rendered in components/shell.html. */
export function icon(name, className = "") {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", `icon ${className}`.trim());
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", `#i-${name}`);
    svg.append(use);
    return svg;
}
