const button = document.querySelector("[data-go-back]");

// Offer "Go back" only when the previous page is on this site, so it never leads somewhere unexpected.
let cameFromHere = false;
try {
    cameFromHere = !!document.referrer && new URL(document.referrer).origin === window.location.origin;
} catch {
    cameFromHere = false;
}
if (cameFromHere && window.history.length > 1) {
    button.hidden = false;
    button.addEventListener("click", () => window.history.back());
}
