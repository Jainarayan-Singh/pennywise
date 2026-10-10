/** Display formatting only. Amounts stay strings end to end; the browser never does money arithmetic. */

export function formatMoney(amount, currency, locale) {
    // Intl formats the decimal string; no Number() math is performed on it.
    try {
        return new Intl.NumberFormat(locale, { style: "currency", currency }).format(amount);
    } catch {
        return `${amount} ${currency}`;
    }
}

export function formatDate(isoDate, locale) {
    // Parse as a calendar date (not a UTC instant) so it never shifts by timezone.
    const [year, month, day] = isoDate.split("-").map(Number);
    return new Date(year, month - 1, day).toLocaleDateString(locale, {
        day: "numeric", month: "short", year: "numeric",
    });
}

export function humanize(value) {
    const spaced = value.replace(/_/g, " ");
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
