// Runs before first paint: applies the saved theme and sidebar state (no flash) and, right after a sign-out, keeps the loading screen up.
(function () {
    var THEMES = ["light", "dark", "midnight", "emerald", "sunset"];
    var DEFAULT_THEME = "sunset"; // used until the visitor picks one; a saved choice always wins
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
    var theme = THEMES.indexOf(saved) !== -1 ? saved : DEFAULT_THEME;
    document.documentElement.setAttribute("data-theme", theme);
    if (arriving) document.documentElement.setAttribute("data-arrival", "");
    if (sidebar === "collapsed") document.documentElement.setAttribute("data-sidebar", "collapsed");
})();
