const PREFERRED_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
const TICK_MS = 250;

class VoiceError extends Error {
    constructor(code, message) {
        super(message);
        this.name = "VoiceError";
        this.code = code;
    }
}

/** Recording needs a secure context, a microphone API and MediaRecorder. */
export function voiceSupported() {
    return Boolean(
        window.isSecureContext && navigator.mediaDevices?.getUserMedia && "MediaRecorder" in window && "AudioContext" in window,
    );
}

function describeCaptureError(error) {
    switch (error?.name) {
        case "NotAllowedError":
        case "SecurityError":
            return new VoiceError("permission", "Microphone access is blocked. Allow it in your browser's site settings, or type instead.");
        case "NotFoundError":
        case "OverconstrainedError":
            return new VoiceError("no_device", "No microphone was found. Connect one, or type instead.");
        default:
            return new VoiceError("failed", "The microphone couldn't be started. Try again, or type instead.");
    }
}

/**
 * Start capturing. Resolves with a session whose `result` promise settles when recording stops
 * (via stop(), the time limit, or cancel() which resolves null). The microphone is always released.
 */
export async function startRecording({ maxSeconds, onTick, onLimit }) {
    let stream;
    try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (error) {
        throw describeCaptureError(error);
    }

    const mimeType = PREFERRED_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks = [];
    const startedAt = performance.now();
    let cancelled = false;
    let ticker;

    const result = new Promise((resolve) => {
        recorder.addEventListener("dataavailable", (event) => { if (event.data.size) chunks.push(event.data); });
        recorder.addEventListener("stop", () => {
            clearInterval(ticker);
            for (const track of stream.getTracks()) track.stop();
            resolve(cancelled ? null : { blob: new Blob(chunks, { type: recorder.mimeType }) });
        });
    });

    const finish = () => { if (recorder.state !== "inactive") recorder.stop(); };
    ticker = setInterval(() => {
        const elapsed = (performance.now() - startedAt) / 1000;
        onTick?.(elapsed);
        if (elapsed >= maxSeconds) {
            finish();
            onLimit?.();
        }
    }, TICK_MS);

    recorder.start();
    onTick?.(0);
    return {
        result,
        stop: () => { finish(); return result; },
        cancel: () => { cancelled = true; finish(); return result; },
    };
}
