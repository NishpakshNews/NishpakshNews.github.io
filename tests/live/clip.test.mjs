// The intro recording: it starts on the tap, before the login and the socket (copy of the harness in controller.test.mjs).
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


const msg = (ws, o) => ws.onmessage({ data: JSON.stringify(o) });
const introText = (ws) => ws.sent.filter((m) => /[Ss]ay this one sentence aloud/.test(m.realtimeInput?.text || ""));

test("the recording of the reader's voice plays at once, while the login is still going on, and the guide does not say the intro again", async () => {
  let give; const grantGate = new Promise((r) => { give = r; });
  const w = browser({ clip: true, grantGate });
  const { talk, ev } = make();
  const started = talk.start({ storyId: 7, lang: "en", style: { voice: "Orus" } });
  await tick(30);
  assert.ok(w.fetched.some((u) => u.endsWith("/live/intro-Orus-en.m4a")), "the file of the chosen voice and language");
  assert.equal(w.sockets.length, 0, "no socket yet: the login has not answered");
  assert.equal(w.sources.filter((s) => s.at !== undefined).length, 1, "the recording is already playing");
  await tick(1250);               // the card says "intro" only once the voice is heard: CLIP_LEAD_S (1.2 s) after scheduling (Oct 12 2026)
  assert.ok(ev.states.includes("intro"));
  give();
  await tick(30);
  const ws = w.sockets[0];
  ws.onopen();
  await msg(ws, { setupComplete: {} });
  await tick(20);
  assert.equal(introText(ws).length, 0, "the recording was the intro: the guide is not asked to say it");
  assert.equal(w.taps.length, 0, "the microphone stays shut while the recording plays");
  talk.skipIntro();
  await started;
  await tick(30);
  assert.equal(ev.states.at(-1), "listening");
  assert.equal(w.taps.length, 1);
  talk.stop();
});

test("no recording for that voice: the guide says the intro itself once the socket is ready, as before", async () => {
  const w = browser({ clip: false });
  const { talk, ev } = make();
  const started = talk.start({ storyId: 7, lang: "en", style: { voice: "Orus" } });
  await tick(30);
  const ws = w.sockets[0];
  ws.onopen();
  await msg(ws, { setupComplete: {} });
  await tick(30);
  assert.equal(introText(ws).length, 1);
  await msg(ws, { serverContent: { turnComplete: true } });
  await started;
  await tick(30);
  assert.equal(ev.states.at(-1), "listening");
  talk.stop();
});

test("a recording asked for early (preload) is not fetched again on the tap", async () => {
  const w = browser({ clip: true });
  const { talk } = make();
  talk.preload({ lang: "en", voice: "Kore" });
  talk.preload({ lang: "en", voice: "Kore" });
  const started = talk.start({ storyId: 7, lang: "en" });
  await tick(30);
  assert.equal(w.fetched.filter((u) => u.endsWith("intro-Kore-en.m4a")).length, 1);
  talk.stop();
  await started;
});

test("a stopped conversation takes the recording with it", async () => {
  const w = browser({ clip: true });
  const { talk } = make();
  const started = talk.start({ storyId: 7, lang: "en" });
  await tick(30);
  talk.stop();
  await started;
  assert.ok(w.sources.every((s) => s.stopped || s.at === undefined));
});

test("warm() only wakes the token function (a body of {warm: 1}); the grant and the socket report how long they took", async () => {
  const w = browser({ clip: true, grantBody: { token: "auth_tokens/abc", model: "m", lang: "en", instruction: "R", sentence_ids: ["p0s0"], max_seconds: 480, timing: { login: 300, article: 250, earlier: 800, begin: 900, mint: 1500 } } });
  const bodies = [];
  const real = globalThis.fetch;
  globalThis.fetch = async (url, init) => { if (String(url).endsWith("live-token")) bodies.push(JSON.parse(init.body)); return real(url, init); };
  const metrics = [];
  const { talk } = make({ onMetric: (m) => metrics.push(m) });
  talk.warm();
  await tick(20);
  assert.deepEqual(bodies, [{ warm: 1 }]);
  const started = talk.start({ storyId: 7, lang: "en" });
  await tick(30);
  const grantMetric = metrics.find((m) => "grantMs" in m);
  assert.ok(grantMetric && grantMetric.grantMs >= 0);
  assert.deepEqual(grantMetric.server, { login: 300, article: 250, earlier: 800, begin: 900, mint: 1500 });
  const ws = w.sockets[0];
  ws.onopen();
  await msg(ws, { setupComplete: {} });
  assert.ok(metrics.some((m) => "socketReadyMs" in m));
  talk.stop();
  await started;
  globalThis.fetch = real;
});
