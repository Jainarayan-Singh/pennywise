export function initPasswordToggles() {
    for (const button of document.querySelectorAll("[data-password-toggle]")) {
        const input = document.getElementById(button.dataset.passwordToggle);
        button.addEventListener("click", () => {
            const reveal = input.type === "password";
            input.type = reveal ? "text" : "password";
            button.setAttribute("aria-pressed", String(reveal));
            button.setAttribute("aria-label", reveal ? "Hide password" : "Show password");
        });
    }
}
