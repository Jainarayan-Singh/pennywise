const TARGET_RATE = 16000;

function encodeWav(samples, rate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const writeText = (offset, text) => { for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i)); };

    writeText(0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeText(8, "WAVE");
    writeText(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, 1, true); // mono
    view.setUint32(24, rate, true);
    view.setUint32(28, rate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeText(36, "data");
    view.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i += 1) {
        const clipped = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(44 + i * 2, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true);
    }
    return new Blob([buffer], { type: "audio/wav" });
}

/**
 * Decode whatever the browser recorded (webm/opus, mp4/aac, ...) and re-encode it as 16 kHz mono WAV.
 * One well-defined format means the server can verify the real duration and the provider never has to
 * guess the codec.
 */
export async function recordingToWav(blob) {
    const context = new AudioContext();
    let decoded;
    try {
        decoded = await context.decodeAudioData(await blob.arrayBuffer());
    } finally {
        context.close();
    }
    const offline = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * TARGET_RATE)), TARGET_RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    return { wav: encodeWav(rendered.getChannelData(0), TARGET_RATE), durationMs: Math.round(decoded.duration * 1000) };
}
