// Runs before first paint: applies the saved theme and sidebar state (no flash) and, right after a sign-out, keeps the loading screen up.
(function () {
    var saved = null;
    var arriving = false;
    var sidebar = null;
    try {
        sidebar = localStorage.getItem("sidebar");
        saved = localStorage.getItem("theme");
        arriving = sessionStorage.getItem("transition-arrival") === "1";
        sessionStorage.removeItem("transition-arrival");
    } catch (error) {
        saved = null;
    }
    var prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    var theme = saved === "light" || saved === "dark" ? saved : prefersDark ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", theme);
    if (arriving) document.documentElement.setAttribute("data-arrival", "");
    if (sidebar === "collapsed") document.documentElement.setAttribute("data-sidebar", "collapsed");
})();
