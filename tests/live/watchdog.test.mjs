// The stall watchdog, against a fake browser (copy of the harness in controller.test.mjs; these tests run in real time, about 4 s each).
// Before: the controller against a fake browser: no microphone, no speakers, no Gemini. What it checks is the logic around
// them: the order of things, interruptions, failures, and that nothing is left running at the end.
import test from "node:test";
import assert from "node:assert/strict";
import { createTalk, int16ToBase64 } from "../../live/talk.js";

function browser({ micFails = false, grantStatus = 200, grantBody, clip = false, micGate, grantGate } = {}) {   // micGate / grantGate: a promise the test settles by hand, to stop in the middle of connecting
  const w = { sockets: [], sources: [], tracks: [], closedCtx: false, fetched: [], taps: [], spoke: [] };
  class Ctx {
    constructor() { this.sampleRate = 48000; this.currentTime = 0; this.state = "running"; this.destination = {}; this.audioWorklet = { addModule: async () => {} }; }
    async resume() {}
    createBuffer(_c, n, rate) { return { duration: n / rate, copyToChannel() {} }; }
    createBufferSource() { const s = { connect() {}, start(t) { s.at = t; }, stop() { s.stopped = true; }, onended: null, playbackRate: { value: 1 } }; w.sources.push(s); return s; }
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createGain() { return { gain: {}, connect() {} }; }
    async decodeAudioData() { return { duration: 3 }; }
    close() { w.closedCtx = true; this.state = "closed"; }
  }
  class Tap { constructor() { this.port = {}; w.taps.push(this); } connect() {} disconnect() {} }
  class Sock {
    constructor(url) { this.url = url; this.readyState = 1; this.sent = []; w.sockets.push(this); }
    send(m) { this.sent.push(JSON.parse(m)); }
    close() { this.readyState = 3; }
  }
  Object.assign(globalThis, {
    window: globalThis, AudioContext: Ctx, AudioWorkletNode: Tap, WebSocket: Sock,
    fetch: async (url, init) => {
      w.fetched.push(String(url));
      if (String(url).endsWith("live-token")) {
        if (grantGate) await grantGate;
        return { ok: grantStatus === 200, status: grantStatus, json: async () => grantBody || { token: "auth_tokens/abc", model: "gemini-3.8-live", lang: "en", instruction: "RULES", sentence_ids: ["p0s0", "p0s1"], max_seconds: 480 } };
      }
      if (String(url).endsWith("intro.json")) return { ok: true, json: async () => ({ pause_seconds: 0.9, en: ["Hello.", "What?"], hi: ["नमस्ते।", "क्या?"] }) };
      if (String(url).endsWith(".m4a")) return clip ? { ok: true, arrayBuffer: async () => new ArrayBuffer(8) } : { ok: false };
      return { ok: false, json: async () => ({}) };
    },
  });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: { mediaDevices: { getUserMedia: async () => {
    if (micGate) await micGate;
    if (micFails) throw new Error("denied");
    const t = { stop() { t.stopped = true; } }; w.tracks.push(t); return { getTracks: () => [t] };
  } } } });
  return w;
}

function make(extra = {}) {
  const ev = { states: [], highlights: [], errors: [], ends: [], lines: [], grants: [] };
  const talk = createTalk({
    tokenUrl: "https://x/functions/v1/live-token", getHeaders: async () => ({ apikey: "k", Authorization: "Bearer t" }), introBase: "/live/",
    onState: (s) => ev.states.push(s), onHighlight: (id) => ev.highlights.push(id), onError: (e) => ev.errors.push(e.code),
    onEnd: (e) => ev.ends.push(e.reason), onTranscript: (l) => ev.lines.push(l), onGrant: (g) => ev.grants.push(g), ...extra,
  });
  return { talk, ev };
}
const tick = (ms = 5) => new Promise((r) => setTimeout(r, ms));


const ASKED = { toolCall: { functionCalls: [{ id: "1", name: "highlight", args: { sentence_id: "p0s0" } }] } };
const msg = (ws, o) => ws.onmessage({ data: JSON.stringify(o) });

// a conversation that is listening, then the reader says something and stops
async function asked(extra = {}) {
  const w = browser(extra);
  const { talk, ev } = make();
  const started = talk.start({ storyId: 7, lang: "en" });
  await tick(20);
  const ws = w.sockets[0];
  ws.onopen();
  await msg(ws, { setupComplete: {} });
  await tick(20);
  await msg(ws, { serverContent: { turnComplete: true } });            // the intro is finished
  await started;
  w.taps[0].port.onmessage({ data: new Float32Array(1600).fill(0.3) });      // the reader speaks...
  await tick(1000);                                                          // ...and stops: the page is now waiting for the answer
  assert.equal(ev.states.at(-1), "thinking");
  return { w, ws, talk, ev };
}
const nudges = (ws) => ws.sent.filter((m) => m.realtimeInput?.text === "Go ahead and answer now.");

test("the guide answered about a highlight and then said nothing: it is told to go on, once", async () => {
  const { ws, talk } = await asked();
  await msg(ws, ASKED);
  const reply = ws.sent.at(-1).toolResponse.functionResponses[0];
  assert.equal(reply.scheduling, undefined, "a blocking function is answered so that the model carries on");
  assert.equal(nudges(ws).length, 0);
  await tick(2300);
  assert.equal(nudges(ws).length, 1);
  await tick(1000);
  assert.equal(nudges(ws).length, 1, "only once per question");
  talk.stop();
});

test("the guide answers by itself: nobody tells it to go on", async () => {
  const { ws, talk } = await asked();
  await msg(ws, ASKED);
  await msg(ws, { serverContent: { modelTurn: { parts: [{ inlineData: { mimeType: "audio/pcm;rate=24000", data: int16ToBase64(new Int16Array(2400)) } }] } } });
  await tick(2600);
  assert.equal(nudges(ws).length, 0);
  talk.stop();
});
