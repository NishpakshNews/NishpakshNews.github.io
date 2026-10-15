// The recap's conversation in the browser module (owner, Oct 12 2026): same controller, but it asks the function for the recap, uses the recap's
// own intro recording and words, and can light up a story of the recap. Harness as in clip.test.mjs.
import test from "node:test";
import assert from "node:assert/strict";
import { createTalk, LiveProtocol } from "../../live/talk.js";

function browser({ clip = false } = {}) {
  const w = { sockets: [], sources: [], fetched: [], bodies: [] };
  class Ctx {
    constructor() { this.sampleRate = 48000; this.currentTime = 0; this.state = "running"; this.destination = {}; this.audioWorklet = { addModule: async () => {} }; }
    async resume() {}
    createBuffer(_c, n, rate) { return { duration: n / rate, copyToChannel() {} }; }
    createBufferSource() { const s = { connect() {}, start(t) { s.at = t; }, stop() { s.stopped = true; }, onended: null, playbackRate: { value: 1 } }; w.sources.push(s); return s; }
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createGain() { return { gain: {}, connect() {} }; }
    async decodeAudioData() { return { duration: 3 }; }
    close() { this.state = "closed"; }
  }
  class Sock { constructor(url) { this.url = url; this.readyState = 1; this.sent = []; w.sockets.push(this); } send(m) { this.sent.push(JSON.parse(m)); } close() { this.readyState = 3; } }
  Object.assign(globalThis, {
    window: globalThis, AudioContext: Ctx, AudioWorkletNode: class { constructor() { this.port = {}; } connect() {} disconnect() {} }, WebSocket: Sock,
    fetch: async (url, init) => {
      w.fetched.push(String(url));
      if (String(url).endsWith("live-token")) {
        w.bodies.push(JSON.parse(init.body));
        return { ok: true, status: 200, json: async () => ({ token: "auth_tokens/abc", model: "m", lang: "en", instruction: "RULES", kind: "recap", sentence_ids: ["s11", "s12"], max_seconds: 480 }) };
      }
      if (String(url).endsWith("intro.json")) return { ok: true, json: async () => ({ pause_seconds: 0.9, en: ["Hello.", "About this story?"], hi: ["नमस्ते।", "इस ख़बर?"], recap_en: ["Hello.", "About today's news?"], recap_hi: ["नमस्ते।", "आज की ख़बरें?"] }) };
      if (String(url).endsWith(".m4a")) return clip ? { ok: true, arrayBuffer: async () => new ArrayBuffer(8) } : { ok: false };
      return { ok: false, json: async () => ({}) };
    },
  });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: { mediaDevices: { getUserMedia: async () => { const t = { stop() {} }; return { getTracks: () => [t] }; } } } });
  return w;
}
const make = () => createTalk({ tokenUrl: "https://x/functions/v1/live-token", getHeaders: async () => ({}), introBase: "/live/" });
const tick = (ms = 5) => new Promise((r) => setTimeout(r, ms));
const msg = (ws, o) => ws.onmessage({ data: JSON.stringify(o) });

test("a recap conversation asks the function for the recap's day, not for a story", async () => {
  const w = browser({ clip: true });
  const talk = make();
  const started = talk.start({ recap: "2026-10-12", lang: "en", style: { voice: "Kore" } });
  await tick(30);
  assert.deepEqual(w.bodies[0], { recap: "2026-10-12", lang: "en", style: { voice: "Kore" } });
  talk.stop(); await started;
});

test("it plays the RECAP's recording (intro-recap-...), and an article's conversation still plays the article's", async () => {
  const w = browser({ clip: true });
  const talk = make();
  const a = talk.start({ recap: "2026-10-12", lang: "hi", style: { voice: "Orus" } });
  await tick(30);
  assert.ok(w.fetched.some((u) => u.endsWith("/live/intro-recap-Orus-hi.m4a")));
  talk.stop(); await a;
  const w2 = browser({ clip: true });
  const t2 = make();
  const b = t2.start({ storyId: 7, lang: "en", style: { voice: "Orus" } });
  await tick(30);
  assert.ok(w2.fetched.some((u) => u.endsWith("/live/intro-Orus-en.m4a")));
  assert.ok(!w2.fetched.some((u) => u.includes("intro-recap")));
  t2.stop(); await b;
});

test("preload takes the kind too, so the recap's recording can be fetched when the recap opens", async () => {
  const w = browser({ clip: true });
  const talk = make();
  talk.preload({ lang: "en", voice: "Kore", kind: "recap" });
  await tick(10);
  assert.ok(w.fetched.includes("/live/intro-recap-Kore-en.m4a"));
});

test("without a recording the guide says the RECAP's words, not the article's", async () => {
  const w = browser({ clip: false });
  const talk = make();
  const started = talk.start({ recap: "2026-10-12", lang: "en", style: { voice: "Orus" } });
  await tick(30);
  const ws = w.sockets[0];
  ws.onopen();
  await msg(ws, { setupComplete: {} });
  await tick(30);
  const said = ws.sent.filter((m) => /[Ss]ay this one sentence aloud/.test(m.realtimeInput?.text || ""));
  assert.equal(said.length, 1);
  assert.match(said[0].realtimeInput.text, /About today's news\?/);
  assert.doesNotMatch(said[0].realtimeInput.text, /this story/);
  await msg(ws, { serverContent: { turnComplete: true } });
  await started; talk.stop();
});

test("the guide lights a story of the recap by its id, and an id that is not in the recap is ignored", () => {
  const lit = [];
  const p = new LiveProtocol({ sentenceIds: ["s11", "s12"], send() {}, on: { highlight: (id) => lit.push(id) } });
  p.handle({ toolCall: { functionCalls: [{ id: "1", name: "highlight", args: { sentence_id: "s12" } }, { id: "2", name: "highlight", args: { sentence_id: "s99" } }, { id: "3", name: "highlight", args: { sentence_id: "p0s0" } }] } });
  assert.deepEqual(lit, ["s12"]);
});
