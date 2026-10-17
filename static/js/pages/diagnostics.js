import { getJson } from "../services/api-client.js";
import { showSkeleton, showState } from "../components/state.js";
import { toast } from "../components/toast.js";

const content = document.getElementById("diagnostics-content");
const recheck = document.getElementById("recheck-button");

function statusCard(title, ok, headline, detail, rows = []) {
    const card = document.createElement("article");
    card.className = "card stat";

    const heading = document.createElement("h2");
    heading.className = "stat__title";
    heading.textContent = title;

    const badge = document.createElement("span");
    badge.className = `badge ${ok ? "badge--success" : "badge--danger"}`;
    badge.textContent = headline;

    const text = document.createElement("p");
    text.className = "muted small";
    text.textContent = detail;
    card.append(heading, badge, text);

    if (rows.length) {
        const list = document.createElement("dl");
        list.className = "stat__rows";
        for (const [label, value] of rows) {
            const dt = document.createElement("dt");
            dt.textContent = label;
            const dd = document.createElement("dd");
            dd.textContent = value;
            list.append(dt, dd);
        }
        card.append(list);
    }
    return card;
}

function render({ application, database }) {
    const rows = [];
    if (database.engine) rows.push(["Engine", database.engine]);
    if (database.server_version) rows.push(["Server version", database.server_version]);
    if (database.latency_ms !== undefined) rows.push(["Response time", `${database.latency_ms} ms`]);
    if (!database.connected) rows.push(["Reason", database.reason]);

    content.replaceChildren(
        statusCard("Application", true, "Running", `${application.name} (${application.environment})`),
        statusCard("Database", database.connected, database.connected ? "Connected" : "Not connected", database.message, rows),
    );
}

async function load() {
    recheck.disabled = true;
    showSkeleton(content, 3);
    try {
        render(await getJson("/api/v1/status"));
    } catch (error) {
        showState(content, {
            kind: "error", iconName: "alert-circle", title: "Couldn't reach the server",
            text: error.message, actionLabel: "Try again", onAction: load,
        });
        toast.error(error.message);
    } finally {
        recheck.disabled = false;
    }
}

recheck.addEventListener("click", load);
load();
