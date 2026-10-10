import { ApiRequestError, deleteJson, getJson, postForm, postJson, requestJson } from "../services/api-client.js";
import { setDateValue } from "../components/datepicker.js";
import { confirmAction } from "../components/dialog.js";
import { setSelectValue } from "../components/dropdown.js";
import { clearFieldErrors, fillSelect, setAlert, setBusy, showFieldErrors } from "../components/form-helpers.js";
import { icon } from "../components/icon.js";
import { showState } from "../components/state.js";
import { toast } from "../components/toast.js";
import { startRecording, voiceSupported } from "../components/voice-recorder.js";
import { recordingToWav } from "../utils/audio-wav.js";
import { formatDate, formatMoney, humanize } from "../utils/format.js";

const { locale, voice: voiceFlag, maxAudio } = document.getElementById("main-content").dataset;
const DRAFT_KEY = "activeDraftId";
const CONSENT_KEY = "voiceConsent";
const SLOW_NOTICE_MS = 8000;
const MAX_AUDIO_SECONDS = Number(maxAudio) || 60;

const els = {
    conversation: document.getElementById("conversation"),
    composer: document.getElementById("composer"),
    text: document.getElementById("composer-text"),
    send: document.getElementById("send-button"),
    draftCard: document.getElementById("draft-card"),
    status: document.getElementById("draft-status"),
    rows: document.getElementById("draft-rows"),
    hint: document.getElementById("draft-hint"),
    confirm: document.getElementById("confirm-button"),
    edit: document.getElementById("edit-button"),
    discard: document.getElementById("discard-button"),
    saved: document.getElementById("saved-card"),
    editDialog: document.getElementById("draft-edit-dialog"),
    editForm: document.getElementById("draft-edit-dialog-form"),
    editAlert: document.getElementById("draft-edit-dialog-alert"),
    mic: document.getElementById("mic-button"),
    recorder: document.getElementById("recorder"),
    recorderTime: document.getElementById("recorder-time"),
    recorderStop: document.getElementById("recorder-stop"),
    recorderCancel: document.getElementById("recorder-cancel"),
    voiceStatus: document.getElementById("voice-status"),
};

const state = { draft: null, lookups: null, session: null, fromVoice: false };

const storage = {
    get: () => { try { return sessionStorage.getItem(DRAFT_KEY); } catch { return null; } },
    set: (id) => { try { sessionStorage.setItem(DRAFT_KEY, id); } catch { /* resume is a convenience only */ } },
    clear: () => { try { sessionStorage.removeItem(DRAFT_KEY); } catch { /* ignore */ } },
};

// ---------- conversation ----------

function bubble(kind, text) {
    const element = document.createElement("div");
    element.className = `bubble bubble--${kind}`;
    element.textContent = text;
    els.conversation.append(element);
    els.conversation.scrollTop = els.conversation.scrollHeight;
    return element;
}

function workingBubble(message = "Understanding your message…") {
    const element = document.createElement("div");
    element.className = "bubble bubble--working";
    const label = document.createElement("span");
    label.textContent = message;
    const spinner = document.createElement("span");
    spinner.className = "spinner";
    spinner.setAttribute("aria-hidden", "true");
    element.append(spinner, label);
    els.conversation.append(element);
    els.conversation.scrollTop = els.conversation.scrollHeight;
    const timer = setTimeout(() => { label.textContent = "Still working. The free AI tier can take up to 40 seconds."; }, SLOW_NOTICE_MS);
    return { remove: () => { clearTimeout(timer); element.remove(); } };
}

function errorBubble(error) {
    const element = document.createElement("div");
    element.className = "bubble bubble--error";
    const message = document.createElement("span");
    message.textContent = error.message;
    element.append(message);
    if (error.status === 429 || error.status >= 500) {
        const link = document.createElement("a");
        link.href = "/transactions";
        link.textContent = "Add it manually instead";
        element.append(link);
    }
    els.conversation.append(element);
    els.conversation.scrollTop = els.conversation.scrollHeight;
}

// ---------- draft card ----------

function displayValue(row, currency) {
    if (row.value === null) return null;
    if (row.display) return row.display;
    switch (row.key) {
        case "amount": return formatMoney(row.value, currency, locale);
        case "transaction_date": return formatDate(row.value, locale);
        case "transaction_type":
        case "payment_method": return humanize(row.value);
        default: return row.value;
    }
}

function sourceBadge(row) {
    const badge = document.createElement("span");
    switch (row.source) {
        case "missing": badge.className = "badge badge--danger"; badge.textContent = "Needed"; break;
        case "inferred": badge.className = "badge badge--primary"; badge.textContent = `Suggested${row.note ? ` ${row.note}` : ""}`; break;
        case "default": badge.className = "badge"; badge.textContent = "Default"; break;
        case "rule": badge.className = "badge"; badge.textContent = row.note ?? "Resolved"; break;
        default: return null;
    }
    return badge;
}

function renderDraft(draft) {
    state.draft = draft;
    storage.set(draft.id);
    els.draftCard.hidden = false;
    els.saved.hidden = true;

    const ready = draft.status === "ready_for_review";
    els.status.className = `badge ${ready ? "badge--success" : "badge--warning"}`;
    els.status.textContent = ready ? "Ready to save" : "Needs an answer";
    els.confirm.disabled = !ready;
    els.hint.hidden = ready;
    els.hint.textContent = "Answer the question above, or use Edit details, to continue.";

    els.rows.replaceChildren(...draft.fields.map((row) => {
        const wrapper = document.createElement("div");
        wrapper.className = "draft-row";
        const term = document.createElement("dt");
        term.textContent = row.label;
        const description = document.createElement("dd");
        const text = displayValue(row, draft.currency);
        if (text === null) {
            description.className = "is-unset";
            description.textContent = row.key === "category_id" ? "Uncategorised" : "—";
        } else {
            description.append(text);
        }
        const badge = sourceBadge(row);
        if (badge) description.append(badge);
        wrapper.append(term, description);
        return wrapper;
    }));
}

function resetAssistant({ keepConversation = false } = {}) {
    state.draft = null;
    storage.clear();
    els.draftCard.hidden = true;
    els.saved.hidden = true;
    els.text.value = "";
    if (!keepConversation) {
        els.conversation.replaceChildren();
        bubble("assistant", "Tell me what you spent or earned. I'll ask only for what's missing.");
    }
    els.text.focus();
}

// ---------- sending ----------

function setComposerBusy(busy) {
    els.text.disabled = busy;
    els.send.disabled = busy;
    if (busy) els.send.setAttribute("data-loading", "");
    else els.send.removeAttribute("data-loading");
}

async function send(event) {
    event.preventDefault();
    const text = els.text.value.trim();
    if (!text) return;
    bubble("user", text);
    const working = workingBubble();
    setComposerBusy(true);
    try {
        const data = state.draft
            ? await postJson(`/api/v1/ai/expense-drafts/${state.draft.id}/message`, { text })
            : await postJson("/api/v1/ai/expense-drafts", { text, source: state.fromVoice ? "voice" : "text" });
        working.remove();
        els.text.value = "";
        state.fromVoice = false;
        bubble("assistant", data.draft.question ?? "I have what I need. Please check the details below, then confirm to save.");
        renderDraft(data.draft);
    } catch (error) {
        working.remove();
        if (error.code === "draft_expired" || error.code === "draft_closed" || error.status === 404) {
            toast.warning("That draft is no longer available. Describe the expense again.");
            resetAssistant({ keepConversation: true });
            els.text.value = text;
            return;
        }
        errorBubble(error instanceof ApiRequestError ? error : new ApiRequestError("Something went wrong."));
        if (error.details?.text) toast.error(error.details.text);
    } finally {
        setComposerBusy(false);
        els.text.focus();
    }
}

// ---------- confirm / discard ----------

async function confirmDraft() {
    els.confirm.disabled = true;
    els.confirm.setAttribute("data-loading", "");
    try {
        const payload = await requestJson("POST", `/api/v1/ai/expense-drafts/${state.draft.id}/confirm`);
        const { transaction } = payload.data;
        storage.clear();
        state.draft = null;
        els.draftCard.hidden = true;
        showState(els.saved, {
            iconName: "check-circle",
            title: "Transaction saved",
            text: `${humanize(transaction.type)} of ${formatMoney(transaction.amount, transaction.currency, locale)} on ${formatDate(transaction.transaction_date, locale)}.`,
        });
        const actions = document.createElement("div");
        actions.className = "btn-group";
        const again = document.createElement("button");
        again.type = "button";
        again.className = "btn btn--primary";
        again.append(icon("plus"), "Add another");
        again.addEventListener("click", () => resetAssistant());
        const view = document.createElement("a");
        view.className = "btn btn--secondary";
        view.href = "/transactions";
        view.textContent = "View transactions";
        actions.append(again, view);
        els.saved.querySelector(".state").append(actions);
        els.saved.hidden = false;
        toast.success("Transaction saved.");
    } catch (error) {
        toast.error(error.message);
        if (error.details) toast.warning("Use Edit details to fix the highlighted problem, then confirm again.");
        els.confirm.disabled = state.draft?.status !== "ready_for_review";
    } finally {
        els.confirm.removeAttribute("data-loading");
    }
}

async function discardDraft() {
    const discarded = await confirmAction({
        title: "Discard this draft?",
        message: "Nothing has been saved yet. The details you've entered here will be thrown away.",
        confirmLabel: "Discard draft",
        action: () => deleteJson(`/api/v1/ai/expense-drafts/${state.draft.id}`),
    });
    if (discarded) {
        toast.info("Draft discarded.");
        resetAssistant();
    }
}

// ---------- edit details ----------

async function loadLookups() {
    if (!state.lookups) {
        const [categories, accounts] = await Promise.all([getJson("/api/v1/categories"), getJson("/api/v1/accounts")]);
        state.lookups = { categories: categories.categories, accounts: accounts.accounts };
    }
    return state.lookups;
}

function fieldValue(key) {
    return state.draft.fields.find((row) => row.key === key)?.value ?? "";
}

function refreshEditCategories() {
    const type = els.editForm.elements.transaction_type.value;
    const select = els.editForm.elements.category_id;
    const options = state.lookups.categories.filter((c) => c.kind === type).map((c) => ({ value: c.id, label: c.name }));
    fillSelect(select, options, { selected: select.value || fieldValue("category_id") });
}

async function openEdit() {
    try {
        const { accounts } = await loadLookups();
        const form = els.editForm.elements;
        clearFieldErrors(els.editForm);
        setAlert(els.editAlert, "");
        form.transaction_type.value = fieldValue("transaction_type") || "expense";
        form.amount.value = fieldValue("amount");
        setDateValue(form.transaction_date, fieldValue("transaction_date"));
        setSelectValue(form.payment_method, fieldValue("payment_method"));
        form.merchant.value = fieldValue("merchant");
        form.description.value = fieldValue("description");
        fillSelect(form.account_id, accounts.map((a) => ({ value: a.id, label: `${a.name} (${a.currency})` })), { selected: fieldValue("account_id") });
        fillSelect(form.category_id, [], {});
        refreshEditCategories();
        document.getElementById("edit-currency").textContent = state.draft.currency;
        els.editDialog.showModal();
        form.amount.focus();
    } catch (error) {
        toast.error(error.message);
    }
}

async function saveEdit(event) {
    event.preventDefault();
    clearFieldErrors(els.editForm);
    setAlert(els.editAlert, "");
    const form = els.editForm.elements;
    const body = {
        transaction_type: form.transaction_type.value,
        transaction_date: form.transaction_date.value || null,
        category_id: form.category_id.value || null,
        account_id: form.account_id.value || null,
        payment_method: form.payment_method.value || null,
        merchant: form.merchant.value.trim() || null,
        description: form.description.value.trim() || null,
    };
    if (form.amount.value.trim()) body.amount = form.amount.value.trim();
    if (!body.transaction_date) delete body.transaction_date;
    setBusy(els.editForm, true);
    try {
        const data = await requestJson("PATCH", `/api/v1/ai/expense-drafts/${state.draft.id}`, { body }).then((p) => p.data);
        els.editDialog.close();
        renderDraft(data.draft);
        toast.success("Details updated.");
        if (data.draft.question) bubble("assistant", data.draft.question);
    } catch (error) {
        if (error.details) {
            showFieldErrors(els.editForm, error.details);
            setAlert(els.editAlert, "Please correct the highlighted fields.");
        } else {
            setAlert(els.editAlert, error.message);
        }
    } finally {
        setBusy(els.editForm, false);
    }
}

// ---------- voice ----------

const consent = {
    given: () => { try { return localStorage.getItem(CONSENT_KEY) === "1"; } catch { return false; } },
    remember: () => { try { localStorage.setItem(CONSENT_KEY, "1"); } catch { /* asked again next time */ } },
};

const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
const announce = (message) => { els.voiceStatus.textContent = message; };

function setRecordingUi(recording) {
    els.recorder.hidden = !recording;
    els.mic.disabled = recording;
    els.text.disabled = recording;
    els.send.disabled = recording;
}

async function beginRecording() {
    if (!consent.given()) {
        const agreed = await confirmAction({
            title: "Use your voice?",
            message: `Your recording (up to ${MAX_AUDIO_SECONDS} seconds) is sent to Google to be turned into text. This app doesn't keep the audio. You'll see the text and can fix it before anything is saved.`,
            confirmLabel: "Allow and record",
            tone: "primary",
        });
        if (!agreed) return;
        consent.remember();
    }
    try {
        state.session = await startRecording({
            maxSeconds: MAX_AUDIO_SECONDS,
            onTick: (seconds) => { els.recorderTime.textContent = `Recording ${clock(seconds)} / ${clock(MAX_AUDIO_SECONDS)}`; },
            onLimit: () => { toast.info(`Reached the ${MAX_AUDIO_SECONDS}-second limit. Using what you said.`); finishRecording(); },
        });
        setRecordingUi(true);
        announce("Recording started. Speak now.");
        els.recorderStop.focus();
    } catch (error) {
        toast.error(error.message);
    }
}

async function finishRecording() {
    const session = state.session;
    if (!session) return;
    state.session = null;
    setRecordingUi(false);
    announce("Recording stopped. Converting to text.");
    const recorded = await session.stop();
    if (!recorded) return;

    const working = workingBubble("Turning your voice into text…");
    try {
        const { wav, durationMs } = await recordingToWav(recorded.blob);
        const form = new FormData();
        form.append("audio", wav, "voice.wav");
        form.append("duration_ms", String(durationMs));
        const { transcript } = await postForm("/api/v1/ai/transcriptions", form);
        working.remove();
        els.text.value = transcript;
        state.fromVoice = true;
        bubble("assistant", "Here's what I heard. Check the text, fix anything that's wrong, then press Send.");
        announce("Transcript ready. Review it, then send.");
    } catch (error) {
        working.remove();
        const message = error instanceof ApiRequestError ? error.message : "That recording couldn't be read. Try again, or type it.";
        errorBubble(new ApiRequestError(message, { status: error.status ?? 0 }));
        announce(message);
    } finally {
        els.text.focus();
    }
}

async function cancelRecording() {
    const session = state.session;
    state.session = null;
    setRecordingUi(false);
    await session?.cancel();
    announce("Recording cancelled.");
    els.mic.focus();
}

if (voiceFlag === "true") {
    if (voiceSupported()) {
        els.mic.addEventListener("click", beginRecording);
        els.recorderStop.addEventListener("click", finishRecording);
        els.recorderCancel.addEventListener("click", cancelRecording);
    } else {
        els.mic.disabled = true;
        els.mic.dataset.tooltip = "Voice recording isn't supported in this browser";
        els.mic.setAttribute("aria-label", "Voice recording isn't supported in this browser");
    }
}

// ---------- events and resume ----------

els.composer.addEventListener("submit", send);
els.text.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        els.composer.requestSubmit();
    }
});
for (const chip of document.querySelectorAll("[data-example]")) {
    chip.addEventListener("click", () => {
        els.text.value = chip.dataset.example;
        els.text.focus();
    });
}
els.confirm.addEventListener("click", confirmDraft);
els.edit.addEventListener("click", openEdit);
els.discard.addEventListener("click", discardDraft);
els.editForm.addEventListener("submit", saveEdit);
for (const radio of els.editForm.elements.transaction_type) radio.addEventListener("change", refreshEditCategories);

async function resume() {
    const id = storage.get();
    if (!id) return;
    try {
        const { draft } = await getJson(`/api/v1/ai/expense-drafts/${encodeURIComponent(id)}`);
        if (draft.status === "needs_clarification" || draft.status === "ready_for_review") {
            bubble("assistant", draft.question ?? "Welcome back. Your draft is ready to review below.");
            renderDraft(draft);
        } else {
            storage.clear();
        }
    } catch {
        storage.clear();
    }
}

resume();
