// The controller against a fake browser: no microphone, no speakers, no Gemini. What it checks is the logic around
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
    createBufferSource() { const s = { connect() {}, start(t) { s.at = t; }, stop() { s.stopped = true; }, onended: null }; w.sources.push(s); return s; }
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

test("happy path: intro, then the socket says ready, then the microphone opens and audio flows both ways", async () => {
  const w = browser({ clip: true });
  const { talk, ev } = make();
  const started = talk.start({ storyId: 7, lang: "en" });
  // the intro recording is playing: end it by hand (the controller waits for its length on a timer, not for onended)
  await tick(20);
  assert.deepEqual(ev.states, ["connecting", "intro"]);
  assert.match(w.sockets[0].url, /BidiGenerateContentConstrained\?access_token=auth_tokens%2Fabc$/);
  assert.equal(ev.grants[0].instruction, "RULES");
  talk.skipIntro();
  await started;
  // the socket opens: setup goes first, with the instruction from the grant
  const ws = w.sockets[0];
  ws.onopen();
  assert.equal(ws.sent[0].setup.systemInstruction.parts[0].text, "RULES");
  assert.equal(ws.sent[0].setup.model, "models/gemini-3.8-live");
  assert.deepEqual(ev.states.slice(-1), ["intro"]);           // not listening before the server is ready
  await ws.onmessage({ data: JSON.stringify({ setupComplete: {} }) });
  await tick(20);
  assert.equal(ev.states.at(-1), "listening");
  // the reader's voice: 48 kHz float chunk becomes 16 kHz PCM on the socket
  w.taps[0].port.onmessage({ data: new Float32Array(1600).fill(0.3) });
  const audioMsg = ws.sent.at(-1).realtimeInput.audio;
  assert.equal(audioMsg.mimeType, "audio/pcm;rate=16000");
  assert.equal(Buffer.from(audioMsg.data, "base64").length, (1600 / 3 | 0) * 2);
  // the guide's voice: speaking
  await ws.onmessage({ data: JSON.stringify({ serverContent: { modelTurn: { parts: [{ inlineData: { mimeType: "audio/pcm;rate=24000", data: int16ToBase64(new Int16Array(2400)) } }] } } }) });
  assert.equal(ev.states.at(-1), "speaking");
  // the guide lights a sentence, and the made-up one is ignored
  await ws.onmessage({ data: JSON.stringify({ toolCall: { functionCalls: [{ id: "1", name: "highlight", args: { sentence_id: "p0s1" } }, { id: "2", name: "highlight", args: { sentence_id: "p5s5" } }] } }) });
  assert.deepEqual(ev.highlights, ["p0s1"]);
  // the reader talks over the guide: playback stops at once
  const playing = w.sources.filter((s) => s.at !== undefined && !s.stopped && s !== w.sources[0]);
  await ws.onmessage({ data: JSON.stringify({ serverContent: { interrupted: true } }) });
  assert.ok(playing.length > 0 && playing.every((s) => s.stopped));
  assert.equal(ev.states.at(-1), "listening");
  // muting stops the voice and flushes
  talk.setMuted(true);
  assert.deepEqual(ws.sent.at(-1), { realtimeInput: { audioStreamEnd: true } });
  const n = ws.sent.length;
  w.taps[0].port.onmessage({ data: new Float32Array(1600).fill(0.3) });
  assert.equal(ws.sent.length, n);
  // stop: everything is released, and ending twice does nothing
  talk.stop();
  talk.stop();
  assert.deepEqual(ev.ends, ["stopped"]);
  assert.equal(ev.states.at(-1), "ended");
  assert.equal(ws.readyState, 3);
  assert.ok(w.tracks.every((t) => t.stopped));
  assert.ok(w.closedCtx);
});

test("with no recording yet the intro is skipped quietly (no browser voice here), and the conversation still starts", async () => {
  const w = browser();
  const { talk, ev } = make();
  await talk.start({ storyId: 7, lang: "en" });
  w.sockets[0].onopen();
  await w.sockets[0].onmessage({ data: JSON.stringify({ setupComplete: {} }) });
  await tick(20);
  assert.equal(ev.states.at(-1), "listening");
  talk.stop();
});

test("the reader's day is used up: the error says limit, nothing was opened, nothing is left running", async () => {
  const w = browser({ grantStatus: 429, grantBody: { error: "limit" } });
  const { talk, ev } = make();
  await talk.start({ storyId: 7, lang: "en" });
  assert.deepEqual(ev.errors, ["limit"]);
  assert.deepEqual(ev.ends, ["limit"]);
  assert.equal(w.sockets.length, 0);
  assert.ok(w.tracks.every((t) => t.stopped));          // the microphone was released
  assert.equal(talk.state, "ended");
});

test("a refused hour carries the time of the next reset (XX:00) and its scope to the page", async () => {
  browser({ grantStatus: 429, grantBody: { error: "limit", scope: "hour", resets_at: "2026-10-11T09:30:00+00:00" } });
  const seen = [];
  const { talk } = make({ onEnd: (e) => seen.push([e.reason, e.resetsAt, e.scope]) });
  await talk.start({ storyId: 7, lang: "en" });
  assert.deepEqual(seen, [["limit", "2026-10-11T09:30:00+00:00", "hour"]]);
});

test("each refusal has its own code", async () => {
  for (const [status, body, code] of [[401, { error: "login" }, "login"], [503, { error: "busy" }, "busy"], [404, { error: "gone" }, "gone"], [503, { error: "unavailable" }, "unavailable"]]) {
    browser({ grantStatus: status, grantBody: body });
    const { talk, ev } = make();
    await talk.start({ storyId: 7, lang: "en" });
    assert.deepEqual(ev.errors, [code]);
  }
});

test("a blocked microphone stops before anything is asked of the server", async () => {
  const w = browser({ micFails: true });
  const { talk, ev } = make();
  await talk.start({ storyId: 7, lang: "en" });
  assert.deepEqual(ev.errors, ["mic"]);
  assert.ok(!w.fetched.some((u) => u.endsWith("live-token")));
});

test("the socket closing before it was ready is a refusal, with the reason", async () => {
  const w = browser();
  const { talk, ev } = make();
  await talk.start({ storyId: 7, lang: "en" });
  w.sockets[0].onclose({ code: 1007, reason: "bad setup" });
  assert.deepEqual(ev.errors, ["refused"]);
  assert.deepEqual(ev.ends, ["refused"]);
});

test("the server saying goAway ends the conversation cleanly", async () => {
  const w = browser();
  const { talk, ev } = make();
  await talk.start({ storyId: 7, lang: "en" });
  await w.sockets[0].onmessage({ data: JSON.stringify({ setupComplete: {} }) });
  await w.sockets[0].onmessage({ data: JSON.stringify({ goAway: { timeLeft: "10s" } }) });
  assert.deepEqual(ev.ends, ["goaway"]);
  assert.deepEqual(ev.errors, []);
});

test("a conversation can be started again after it ended", async () => {
  const w = browser();
  const { talk, ev } = make();
  await talk.start({ storyId: 7, lang: "en" });
  talk.stop();
  await talk.start({ storyId: 8, lang: "en" });
  assert.equal(w.sockets.length, 2);
  assert.notEqual(talk.state, "ended");
  talk.stop();
  assert.deepEqual(ev.ends, ["stopped", "stopped"]);
});

test("starting while a conversation is running does nothing", async () => {
  const w = browser();
  const { talk } = make();
  await talk.start({ storyId: 7, lang: "en" });
  await talk.start({ storyId: 7, lang: "en" });
  assert.equal(w.sockets.length, 1);
  talk.stop();
});

test("closed while the browser is still asking for the microphone: the microphone is released and nothing is asked of the server", async () => {
  let allow; const micGate = new Promise((r) => { allow = r; });
  const w = browser({ micGate });
  const { talk, ev } = make();
  const started = talk.start({ storyId: 7, lang: "en" });
  await tick(10);
  talk.stop();                                    // the reader pressed close while the permission box was up
  allow();                                        // ...then pressed Allow
  await started;
  await tick(10);
  assert.ok(w.tracks.length === 1 && w.tracks.every((t) => t.stopped));   // the microphone never stays open
  assert.ok(!w.fetched.some((u) => u.endsWith("live-token")));
  assert.equal(w.sockets.length, 0);
  assert.deepEqual(ev.ends, ["stopped"]);
  assert.equal(talk.state, "ended");
});

test("closed while the token is being fetched: no socket is opened, the intro recording is silenced, the microphone is off", async () => {
  let give; const grantGate = new Promise((r) => { give = r; });
  const w = browser({ grantGate, clip: true });
  const { talk, ev } = make();
  const started = talk.start({ storyId: 7, lang: "en" });
  await tick(10);
  talk.stop();
  give();
  await started;
  await tick(10);
  assert.equal(w.sockets.length, 0);
  assert.ok(w.tracks.every((t) => t.stopped));
  assert.ok(w.sources.every((s) => s.stopped || s.at === undefined && s.loop !== true), "nothing is left playing");   // the recording starts on the tap (before the login), so it must be stopped, and so must the keep-alive hiss
  assert.ok(w.sources.filter((s) => s.at !== undefined).every((s) => s.stopped), "the intro recording was stopped");
  assert.deepEqual(ev.ends, ["stopped"]);
});

test("closed and started again while the first start was still waiting: only the second one runs", async () => {
  let give; const grantGate = new Promise((r) => { give = r; });
  const w = browser({ grantGate });
  const { talk, ev } = make();
  const first = talk.start({ storyId: 7, lang: "en" });
  await tick(10);
  talk.stop();
  const second = talk.start({ storyId: 7, lang: "en" });
  give();
  await Promise.all([first, second]);
  await tick(10);
  assert.equal(w.sockets.length, 1);               // not two conversations
  talk.stop();
});

test("the reader's style goes to the function, the voice from the grant goes into setup, and a nudge reaches the socket only when ready", async () => {
  const w = browser({ grantBody: { token: "auth_tokens/abc", model: "m", lang: "en", instruction: "RULES", sentence_ids: ["p0s0"], voice: "Achird", language_code: "en-IN", max_seconds: 480 } });
  let body = null;
  const f = globalThis.fetch;
  globalThis.fetch = async (url, init) => { if (String(url).endsWith("live-token")) body = JSON.parse(init.body); return f(url, init); };
  const { talk } = make();
  await talk.start({ storyId: 7, lang: "en", style: { voice: "Achird", pace: "slow", tone: "news", accent: "neutral" } });
  assert.deepEqual(body, { story_id: 7, lang: "en", style: { voice: "Achird", pace: "slow", tone: "news", accent: "neutral" } });
  const ws = w.sockets[0];
  talk.nudge("From now on, speak slowly.");                       // the server has not said ready yet
  assert.equal(ws.sent.length, 0);
  ws.onopen();
  const setup = ws.sent[0].setup;
  assert.equal(setup.generationConfig.speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName, "Achird");   // the controller sends the nested layout
  assert.equal(setup.generationConfig.speechConfig.languageCode, "en-IN");
  await ws.onmessage({ data: JSON.stringify({ setupComplete: {} }) });
  talk.nudge("From now on, speak slowly.");
  assert.deepEqual(ws.sent.at(-1), { realtimeInput: { text: "From now on, speak slowly." } });
  talk.stop();
  const n = ws.sent.length;
  talk.nudge("after the end");
  assert.equal(ws.sent.length, n);
  globalThis.fetch = f;
});

test("the speaker is kept awake from the tap until the intro is over, and the recording is scheduled well ahead (heard from mid-clip, Oct 12 2026)", async () => {
  let give; const grantGate = new Promise((r) => { give = r; });
  const w = browser({ clip: true, grantGate });
  const { talk } = make();
  const started = talk.start({ storyId: 7, lang: "en", style: { voice: "Orus" } });
  await tick(30);
  const hiss = w.sources.filter((s) => s.loop === true);
  assert.equal(hiss.length, 1, "one looping keep-alive source, started on the tap");
  assert.equal(hiss[0].at, undefined, "started at once, not scheduled");
  assert.ok(!hiss[0].stopped, "still running while the recording has not played");
  const clip = w.sources.filter((s) => s.at !== undefined);
  assert.equal(clip.length, 1);
  assert.ok(clip[0].at >= 0.9, `the recording is scheduled >= 0.9 s ahead of now (was ${clip[0].at})`);
  give();
  await tick(30);
  talk.skipIntro();
  await started;
  assert.ok(hiss[0].stopped, "the hiss stops once the intro is over");
  talk.stop();
});
