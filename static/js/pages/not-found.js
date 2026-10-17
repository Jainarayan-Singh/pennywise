document.querySelector("[data-go-back]").addEventListener("click", () => {
    if (window.history.length > 1) {
        window.history.back();
        return;
    }
    try {
        if (document.referrer && new URL(document.referrer).origin === window.location.origin) {
            window.location.href = document.referrer;
            return;
        }
    } catch {
        // An unreadable referrer falls through to the home page.
    }
    window.location.href = "/";
});

const container = document.querySelector("[data-particles]");
if (container && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const colors = ["var(--color-primary)", "var(--err-purple)", "var(--err-cyan)", "var(--err-amber)"];
    for (let i = 0; i < 40; i += 1) {
        const particle = document.createElement("div");
        particle.className = "err-particle";
        particle.style.setProperty("--left", `${Math.random() * 100}%`);
        particle.style.setProperty("--bottom", `${Math.random() * -20}%`);
        particle.style.setProperty("--size", `${Math.random() * 3 + 1}px`);
        particle.style.setProperty("--tone", colors[Math.floor(Math.random() * colors.length)]);
        particle.style.setProperty("--duration", `${Math.random() * 12 + 8}s`);
        particle.style.setProperty("--delay", `${Math.random() * -15}s`);
        container.append(particle);
    }
}
