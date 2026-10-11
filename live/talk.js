// "Talk to the article": the browser side of a live voice conversation (owner, Oct 11 2026). No design in here: the
// site gives it callbacks and draws whatever it likes. No dependencies; one ES module.
//
//   const talk = createTalk({
//     tokenUrl: `${SUPABASE_URL}/functions/v1/live-token`,
//     getHeaders: async () => ({ apikey: SUPABASE_KEY, Authorization: `Bearer ${await token()}` }),
//     introBase: "/live/",                      // intro.json: the words the guide says first (it says them itself, in its own voice)
//     onState: (s) => ..., onHighlight: (id) => ..., onTranscript: (lines) => ..., onLevel: (rms) => ...,
//     onMetric: ({firstAudioMs, firstToolMs, tools}) => ...,   // how long one answer took to start, after the reader stopped talking
//     onSlow: (slow) => ...,                    // true when the guide has taken more than a few seconds to start answering, false when it starts
//     onGrant: ({instruction, sentenceIds, maxSeconds, daily}) => ...,   // what the guide was given (for testing)
//     onEnd: ({reason}) => ..., onError: ({code, message}) => ...,
//   });
//   await talk.start({ storyId, lang, style });  // style: {voice, pace, tone, accent}, all optional (the function checks them)
//   talk.nudge("From now on, speak slowly.");  // asks the guide to sound different mid-conversation        // from a tap: the browser asks for the microphone then
//   talk.skipIntro(); talk.setMuted(true); talk.stop();
//
// What happens: microphone permission -> the live-token function (login, limits, the article's brief, a one-use Gemini
// token) -> the fixed intro recording plays while the WebSocket opens -> the microphone opens -> the reader talks and can
// interrupt at any time (Gemini detects speech; this module stops its own playback the moment the server says
// "interrupted"). States: idle, connecting, intro, listening, speaking, ended.
//
// Gemini's Live API: https://ai.google.dev/gemini-api/docs/live-api/get-started-websocket (audio in: 16 kHz 16-bit
// PCM; out: 24 kHz). The pure parts (audio conversion, message handling) are exported and tested in node
// (tests/live/talk.test.mjs); the part that needs a browser (microphone, speakers, socket) is `createTalk`.

export const WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained";
export const IN_RATE = 16000;
export const OUT_RATE = 24000;
const INTRO_WAIT_MS = 15000;            // how long the intro waits for the server to be ready
const INTRO_MAX_MS = 30000;             // and for the guide to finish saying it
const THINK_AFTER_MS = 500;            // the reader's voice has been quiet this long: their turn is over, the guide is working on its answer
const THINK_MAX_MS = 60000;            // "thinking" never lasts longer than this (the guide may simply have had nothing to say). It was 20 s: a big question takes longer, and the page then looked as if nothing was happening
const SLOW_AFTER_MS = 2500;            // still no answer this long after the reader stopped: the page is told (onSlow) so it can say "this is a big one, working on it"
const PING_SECONDS = 15;               // how often the page tells the function the conversation is still going
export const IDLE_SECONDS = 45;          // nobody speaking (either side) this long: the conversation ends
export const WRAP_UP_SECONDS = 20;       // before the longest conversation ends, the guide is asked to close

// -- audio conversion (pure) ----------------------------------------------------------------------------------

/** Float samples at `inRate` -> 16-bit PCM at 16 kHz (averaging each window down; no change when already 16 kHz). */
export function floatTo16kPcm(float32, inRate) {
  const ratio = inRate / IN_RATE;
  const n = ratio <= 1 ? float32.length : Math.floor(float32.length / ratio);
  const out = new Int16Array(n);
  for (let i = 0; i < n; i++) {
    let v;
    if (ratio <= 1) v = float32[i];
    else {
      const a = Math.floor(i * ratio), b = Math.max(a + 1, Math.min(float32.length, Math.floor((i + 1) * ratio)));
      let sum = 0;
      for (let j = a; j < b; j++) sum += float32[j];
      v = sum / (b - a);
    }
    v = Math.max(-1, Math.min(1, v));
    out[i] = v < 0 ? Math.round(v * 0x8000) : Math.round(v * 0x7fff);
  }
  return out;
}

export function pcm16ToFloat32(int16) {
  const out = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) out[i] = int16[i] / (int16[i] < 0 ? 0x8000 : 0x7fff);
  return out;
}

export function int16ToBase64(int16) {
  const bytes = new Uint8Array(int16.length * 2);
  const view = new DataView(bytes.buffer);
  for (let i = 0; i < int16.length; i++) view.setInt16(i * 2, int16[i], true);     // little-endian, whatever the device
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

export function base64ToInt16(b64) {
  const s = atob(b64);
  const n = s.length >> 1;
  const view = new DataView(new ArrayBuffer(n * 2));
  for (let i = 0; i < n * 2; i++) view.setUint8(i, s.charCodeAt(i));
  const out = new Int16Array(n);
  for (let i = 0; i < n; i++) out[i] = view.getInt16(i * 2, true);
  return out;
}

export const rms = (f) => { let s = 0; for (let i = 0; i < f.length; i++) s += f[i] * f[i]; return f.length ? Math.sqrt(s / f.length) : 0; };

// -- the noise gate (pure) ------------------------------------------------------------------------------------
// Background noise (a fan, traffic, a TV, people talking far away) used to go to Gemini as it was, so its own speech detector heard
// "someone still talking" and never ended the reader's turn: the guide kept listening instead of answering (owner, Oct 11 2026).
// The gate learns how loud the room is and lets audio through only while something clearly louder than that is happening (the
// reader). Everything else is sent as silence (zeros, so the stream keeps its timing), which the server's detector reads as "the
// reader has finished". The floor follows the quietest recent level: down at once, up slowly (a long sentence must not raise it
// into the speech), and it starts from the first 0.6 s of the microphone. Numbers are first guesses, to be tuned by ear.
export const GATE = { minLevel: 0.012, ratio: 2, hangMs: 500, riseMs: 8000, maxFloor: 0.02, warmMs: 600 };   // Oct 11 2026, evening: it was 0.02 / 2.5 / 400 / 0.03 and shut out a reader who speaks softly (the trailing words of a sentence were lost)

export class NoiseGate {
  constructor(opts = {}) {
    this.c = { ...GATE, ...opts };
    this.floor = null; this.age = 0; this.lastOpen = -Infinity; this.open = false;
  }
  /** One chunk: its rms level and its length in ms. Returns true when the chunk is the reader's voice (let it through). */
  process(level, ms) {
    const c = this.c;
    this.age += ms;
    if (this.floor === null) this.floor = Math.min(level, c.maxFloor);
    else if (this.age < c.warmMs) this.floor = Math.min(c.maxFloor, this.floor + (level - this.floor) * 0.3);       // getting to know the room
    else if (level < this.floor) this.floor = this.floor + (level - this.floor) * 0.5;                                    // quieter: at once
    else this.floor = Math.min(c.maxFloor, this.floor + (level - this.floor) * Math.min(1, ms / c.riseMs));             // louder: slowly
    const threshold = Math.max(c.minLevel, this.floor * c.ratio);
    if (level > threshold) this.lastOpen = this.age;
    this.open = this.age - this.lastOpen <= c.hangMs;
    return this.open;
  }
}

// -- the protocol (pure) --------------------------------------------------------------------------------------

const HIGHLIGHT = {
  name: "highlight",
  description: "Light up the sentence of the article the reader is on that you are about to talk about, so the reader sees it. Call it before you speak about a sentence, with its id (the text in square brackets, for example p2s0). Never say the id aloud.",
  parameters: { type: "OBJECT", properties: { sentence_id: { type: "STRING", description: "The sentence id, for example p2s0" } }, required: ["sentence_id"] },
};

/** The first message on the socket. `instruction` comes from the live-token function (the same text its token is locked
 *  to). `nested`: put responseModalities and speechConfig under generationConfig (the older layout) if the server
 *  rejects the flat one. */
export function setupMessage({ model, instruction, voice = "Kore", languageCode = null, nested = false, tools = null, silenceMs = 500, thinking = null }) {
  const speech = { voiceConfig: { prebuiltVoiceConfig: { voiceName: voice } } };
  if (languageCode) speech.languageCode = languageCode;     // only when the function sends one (off by default: native-audio models pick the language themselves)
  const setup = {
    model: `models/${model}`,
    systemInstruction: { parts: [{ text: instruction }] },
    inputAudioTranscription: {},
    outputAudioTranscription: {},
    // the function declarations come from the server (the token is locked to exactly them); this is only the fallback
    tools: tools || [{ functionDeclarations: [HIGHLIGHT] }],
    // 500-800 ms of silence ends the reader's turn (Google's guidance: shorter splits a sentence at a breath); every answer waits this long first
    realtimeInputConfig: { automaticActivityDetection: { silenceDurationMs: silenceMs, prefixPaddingMs: 100 } },
  };
  if (nested) setup.generationConfig = { responseModalities: ["AUDIO"], speechConfig: speech };
  else { setup.responseModalities = ["AUDIO"]; setup.speechConfig = speech; }
  if (thinking) setup.generationConfig = { ...(setup.generationConfig || {}), thinkingConfig: thinking };    // only when the function sends one (the secret LIVE_THINKING_CONFIG): how long the model may reason before it speaks
  return { setup };
}

/** Understands the server's messages and says what to do about each, through `on`. No audio, no socket: `send(obj)`
 *  and the callbacks are all it touches. `sentenceIds`: the ids the model may highlight (from the article's brief);
 *  anything else it names is ignored, so a made-up id can never light up the wrong sentence. */
export class LiveProtocol {
  constructor({ sentenceIds, send, on }) {
    this.ids = new Set(sentenceIds || []);
    this.send = send;
    this.on = on || {};
    this.lines = [];            // the conversation so far: {role: "you" | "guide", text, open}
  }

  validId(id) {
    const s = String(id || "").trim();
    return this.ids.has(s) || this.ids.has(s.split(".")[0]) ? s : null;
  }

  _said(role, text) {
    if (!text) return;
    const last = this.lines[this.lines.length - 1];
    if (last && last.role === role && last.open) last.text += text;
    else this.lines.push({ role, text, open: true });
    this.on.transcript?.(this.lines.map((l) => ({ role: l.role, text: l.text })));
  }

  _closeLines() { for (const l of this.lines) l.open = false; }

  handle(msg) {
    if (!msg || typeof msg !== "object") return;
    if (msg.setupComplete) this.on.ready?.();
    const sc = msg.serverContent;
    if (sc) {
      for (const part of sc.modelTurn?.parts || []) {
        const d = part.inlineData;
        if (d?.data && String(d.mimeType || "audio/pcm").startsWith("audio/")) this.on.audio?.(base64ToInt16(d.data));
      }
      if (sc.inputTranscription?.text) this._said("you", sc.inputTranscription.text);
      if (sc.outputTranscription?.text) this._said("guide", sc.outputTranscription.text);
      if (sc.interrupted) { this._closeLines(); this.on.interrupted?.(); }
      if (sc.turnComplete) { this._closeLines(); this.on.turnComplete?.(); }
    }
    if (msg.toolCall) this._tools(msg.toolCall.functionCalls || []);
    if (msg.goAway) this.on.goAway?.(msg.goAway.timeLeft);
  }

  _tools(calls) {
    const responses = [];
    for (const fc of calls) {
      this.on.tool?.(fc.name);
      let result = "unknown function";
      if (fc.name === "highlight") {
        const id = this.validId(fc.args?.sentence_id);
        if (id) { this.on.highlight?.(id); result = "ok"; } else result = "no such sentence id";
      }
      // SILENT: the model carries on with what it was saying instead of talking about the call
      responses.push({ id: fc.id, name: fc.name, response: { result }, scheduling: "SILENT" });
    }
    if (responses.length) this.send({ toolResponse: { functionResponses: responses } });
  }
}

// -- the microphone's worklet (runs in the audio thread) ------------------------------------------------------

const WORKLET = `
class PcmTap extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(0); }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) {
      const next = new Float32Array(this.buf.length + ch.length);
      next.set(this.buf); next.set(ch, this.buf.length); this.buf = next;
      if (this.buf.length >= 1600) { this.port.postMessage(this.buf); this.buf = new Float32Array(0); }
    }
    return true;
  }
}
registerProcessor("pcm-tap", PcmTap);`;

export class TalkError extends Error {
  constructor(code, message, extra = {}) { super(message || code); this.code = code; Object.assign(this, extra); }   // extra: for a limit, resetsAt (ISO time) and scope (hour or day)
}

// -- the controller (needs a browser) -------------------------------------------------------------------------

export function createTalk(opts) {
  const o = { introBase: "./", onState() {}, onHighlight() {}, onTranscript() {}, onLevel() {}, onEnd() {}, onError() {}, ...opts };
  let state = "idle", ctx = null, stream = null, ws = null, proto = null, grant = null;
  let tapNode = null, tapSource = null, silent = null, muted = false, micOn = false, ending = false;
  let thinkTimer = null, voiced = false, lastVoice = 0, thinkSince = 0, pingTimer = null, introDone = false, ready = false, introStop = null, introWake = null, readyWake = null;
  let askEnd = 0, firstTool = 0, toolCount = 0;      // timing of one answer: when the reader stopped, when the guide first called a function, when its voice began
  let nextAt = 0, quietTimer = null, idleTimer = null, maxTimer = null, wrapTimer = null, lastActive = 0, slow = false;
  const playing = new Set();
  let runId = 0;                 // each start() is a run; stop() during connecting must stop THAT run from carrying on

  const set = (s) => {
    if (state === s) return;
    state = s;
    if (slow && s !== "thinking") { slow = false; o.onSlow?.(false); }       // the answer started (or the reader spoke again): the "big one" message is over
    o.onState(s);
  };
  const touch = () => { lastActive = Date.now(); };

  // playback: each chunk of the guide's voice is queued right after the one before
  function playPcm(int16) {
    if (!ctx || ending) return;
    touch();
    if (askEnd) {           // the first sound of an answer: how long after the reader stopped (this includes the ~1 s of waiting for the end of their turn)
      const now = Date.now();
      o.onMetric?.({ firstAudioMs: now - askEnd, firstToolMs: firstTool ? firstTool - askEnd : null, tools: toolCount });
      askEnd = 0; firstTool = 0; toolCount = 0;
    }
    const f = pcm16ToFloat32(int16);
    const buf = ctx.createBuffer(1, f.length, OUT_RATE);
    buf.copyToChannel(f, 0);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    const at = Math.max(ctx.currentTime + 0.02, nextAt);
    src.start(at);
    nextAt = at + buf.duration;
    playing.add(src);
    voiced = false;
    set("speaking");
    src.onended = () => {
      playing.delete(src);
      clearTimeout(quietTimer);
      // a short gap between two chunks is not the end of the guide's turn
      quietTimer = setTimeout(() => { if (!playing.size && !ending && micOn) set("listening"); }, 250);
    };
  }

  function interrupt() {            // the reader started talking over the guide: stop at once
    for (const s of playing) { try { s.onended = null; s.stop(); } catch { /* already stopped */ } }
    playing.clear();
    nextAt = 0;
    if (micOn && !ending) set("listening");
  }

  async function startMic() {
    if (micOn || ending || !ctx || !stream) return;
    tapSource = ctx.createMediaStreamSource(stream);
    silent = ctx.createGain();
    silent.gain.value = 0;                // the tap must be connected to run, but must not be heard
    silent.connect(ctx.destination);
    const gate = new NoiseGate();
    const gateOn = grant?.noise_gate !== false;      // the function can switch the gate off (secret LIVE_NOISE_GATE=0): the audio then goes to Gemini as it is; the gate still drives the page's own "reader is talking" cues
    const onChunk = (f32) => {
      if (muted || !ws || ws.readyState !== 1) return;
      const level = rms(f32);
      const voice = gate.process(level, (f32.length / ctx.sampleRate) * 1000);      // the reader, not the room
      o.onLevel(voice ? level : 0);
      if (voice) { touch(); if (!playing.size && state !== "speaking") { voiced = true; lastVoice = Date.now(); if (state === "thinking") set("listening"); } }   // not while the guide speaks: its own voice may leak into the microphone   // talking again: the thinking was early
      ws.send(JSON.stringify({ realtimeInput: { audio: { data: int16ToBase64(floatTo16kPcm(voice || !gateOn ? f32 : new Float32Array(f32.length), ctx.sampleRate)), mimeType: `audio/pcm;rate=${IN_RATE}` } } }));
    };
    try {
      const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
      await ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      tapNode = new AudioWorkletNode(ctx, "pcm-tap");
      tapNode.port.onmessage = (e) => onChunk(e.data);
    } catch {                              // no worklet (an old browser, or a page policy): the older, main-thread way
      tapNode = ctx.createScriptProcessor(2048, 1, 1);
      tapNode.onaudioprocess = (e) => onChunk(new Float32Array(e.inputBuffer.getChannelData(0)));
    }
    tapSource.connect(tapNode);
    tapNode.connect(silent);
    micOn = true;
    touch();
    set("listening");
    // the reader stopped talking and the guide has not started: show it is working on the answer
    thinkTimer = setInterval(() => {
      const now = Date.now();
      if (state === "listening" && voiced && !playing.size && now - lastVoice > THINK_AFTER_MS) { voiced = false; thinkSince = now; askEnd = lastVoice; firstTool = 0; toolCount = 0; set("thinking"); }
      else if (state === "thinking") {
        touch();                                                   // waiting for the guide is not "nobody is speaking": the 45 s idle end must not fire while it works
        if (!slow && now - thinkSince > SLOW_AFTER_MS) { slow = true; o.onSlow?.(true); }
        if (now - thinkSince > THINK_MAX_MS) set("listening");
      }
    }, 150);
  }

  function maybeOpenMic() { if (introDone && ready && !ending) startMic(); }

  async function grantFor(storyId, lang, style) {
    let r;
    try {
      r = await fetch(o.tokenUrl, { method: "POST", headers: { "Content-Type": "application/json", ...(await o.getHeaders()) }, body: JSON.stringify({ story_id: storyId, lang, style }) });
    } catch { throw new TalkError("network", "could not reach Nishpaksh"); }
    let j = {};
    try { j = await r.json(); } catch { /* no body */ }
    if (r.ok && j.token) return j;
    const code = r.status === 401 ? "login" : r.status === 429 ? "limit" : r.status === 503 && j.error === "busy" ? "busy" : r.status === 404 ? "gone" : "unavailable";
    throw new TalkError(code, j.error || `HTTP ${r.status}`, code === "limit" ? { resetsAt: j.resets_at || null, scope: j.scope || "hour" } : {});
  }

  // The intro is spoken by the guide itself (owner, Oct 11 2026: the voice must match everywhere, whichever voice the
  // reader picked): once the server is ready, it is asked to say the fixed words (live/intro.json) and nothing else.
  // The microphone opens only after it has finished, so it never hears itself.
  const sleep = (ms, stopper) => new Promise((resolve) => {
    const t = setTimeout(resolve, ms);
    stopper(() => { clearTimeout(t); resolve(); });
  });
  async function playIntro(lang) {
    let text = null;
    try { text = await (await fetch(`${o.introBase}intro.json`)).json(); } catch { /* none */ }
    const words = text?.[lang];
    if (ending || !Array.isArray(words) || words.length < 2) return;     // no words: the guide just waits for the reader
    set("intro");
    if (!ready) await sleep(INTRO_WAIT_MS, (stop) => { readyWake = stop; });
    readyWake = null;
    if (ending || !ready) return;
    const hindi = lang === "hi";
    proto.send({ realtimeInput: { text: `${hindi ? "In Hindi, say" : "Say"} these two sentences aloud now, exactly as written, with a short pause between them, and nothing else. Do not call any function. First: "${words[0]}" Then: "${words[1]}"` } });
    await sleep(INTRO_MAX_MS, (stop) => { introWake = stop; introStop = stop; });    // the end of the guide's turn
    introWake = null; introStop = null;
    if (ending) return;
    const left = (nextAt - ctx.currentTime) * 1000;                        // what is still queued to play
    if (left > 0) await sleep(left + 150, (stop) => { introStop = stop; });
    introStop = null;
  }

  function openSocket() {
    ws = new WebSocket(`${WS_URL}?access_token=${encodeURIComponent(grant.token)}`);
    proto = new LiveProtocol({
      sentenceIds: grant.sentence_ids,
      send: (m) => ws && ws.readyState === 1 && ws.send(JSON.stringify(m)),
      on: {
        ready: () => { ready = true; readyWake?.(); maybeOpenMic(); },
        audio: playPcm,
        interrupted: interrupt,
        turnComplete: () => { touch(); introWake?.(); if (state === "thinking" && !playing.size) set("listening"); },
        tool: () => { if (askEnd && !firstTool) firstTool = Date.now(); toolCount++; },
        highlight: (id) => { touch(); o.onHighlight(id); },
        transcript: (lines) => { touch(); o.onTranscript(lines); },
        goAway: () => end("goaway"),
      },
    });
    ws.onopen = () => ws.send(JSON.stringify(setupMessage({ model: grant.model, instruction: grant.instruction, voice: grant.voice || undefined, languageCode: grant.language_code || null, nested: true, tools: grant.tools || null, silenceMs: Number(grant.silence_ms) || 500, thinking: grant.thinking || null })));
    ws.onmessage = async (e) => {
      try { proto.handle(JSON.parse(typeof e.data === "string" ? e.data : await e.data.text())); }
      catch { /* one bad frame does not end the conversation */ }
    };
    ws.onerror = () => {};
    ws.onclose = (e) => { if (!ending) end(ready ? "closed" : "refused", `${e.code} ${e.reason || ""}`.trim()); };
  }

  // tell the function the conversation is over, so its place on the site is free at once (best effort)
  function endSession() {
    clearInterval(pingTimer);
    const id = grant?.session;
    if (!id) return;
    grant.session = null;
    Promise.resolve(o.getHeaders()).then((h) => fetch(o.tokenUrl, { method: "POST", keepalive: true, headers: { "Content-Type": "application/json", ...h }, body: JSON.stringify({ end: id }) })).catch(() => {});
  }

  function startPings() {         // "still here", so a closed tab or a dead phone frees its place within 45 s
    const id = grant?.session;
    if (!id) return;
    pingTimer = setInterval(() => {
      Promise.resolve(o.getHeaders()).then((h) => fetch(o.tokenUrl, { method: "POST", headers: { "Content-Type": "application/json", ...h }, body: JSON.stringify({ ping: id }) })).catch(() => {});
    }, PING_SECONDS * 1000);
  }

  function end(reason, detail, extra = {}) {
    if (ending) return;
    ending = true;
    clearTimeout(quietTimer); clearInterval(thinkTimer); clearInterval(idleTimer); clearTimeout(maxTimer); clearTimeout(wrapTimer);
    try { introStop?.(); } catch { /* done */ }
    try { for (const s of playing) { s.onended = null; s.stop(); } } catch { /* done */ }
    playing.clear();
    try { ws && ws.readyState <= 1 && ws.close(1000); } catch { /* done */ }
    try { tapNode && (tapNode.port ? (tapNode.port.onmessage = null) : (tapNode.onaudioprocess = null)); tapNode?.disconnect(); tapSource?.disconnect(); } catch { /* done */ }
    try { stream?.getTracks().forEach((t) => t.stop()); } catch { /* done */ }
    try { ctx && ctx.state !== "closed" && ctx.close(); } catch { /* done */ }
    endSession();
    set("ended");
    if (reason === "refused" || reason === "error") o.onError({ code: reason, message: detail || reason });
    o.onEnd({ reason, detail, ...extra });
  }

  async function start({ storyId, lang, style }) {
    if (state !== "idle" && state !== "ended") return;
    ending = false; muted = false; micOn = false; voiced = false; introDone = false; ready = false; nextAt = 0;
    const run = ++runId;
    const stale = () => ending || run !== runId;     // stopped (or restarted) while this run was waiting on something
    set("connecting");
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      ctx = new AC();
      await ctx.resume();                  // inside the reader's tap, so the browser lets it play
      if (stale()) return;
      let mic;
      try {
        mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
      } catch { throw new TalkError("mic", "the microphone is blocked"); }
      if (stale()) { try { mic.getTracks().forEach((t) => t.stop()); } catch { /* done */ } return; }   // never leave a microphone open
      stream = mic;
      grant = await grantFor(storyId, lang, style);
      if (stale()) return;
      lang = grant.lang || lang;
      if (o.onGrant) o.onGrant({ lang, headline: grant.headline, instruction: grant.instruction, sentenceIds: grant.sentence_ids, maxSeconds: grant.max_seconds, hourly: grant.hourly });
      openSocket();
      startPings();
      await playIntro(lang);
      if (stale()) return;
      introDone = true;
      maybeOpenMic();
      touch();
      idleTimer = setInterval(() => { if (Date.now() - lastActive > IDLE_SECONDS * 1000) end("idle"); }, 2000);
      const max = (grant.max_seconds || 480) * 1000;
      wrapTimer = setTimeout(() => proto?.send({ realtimeInput: { text: "The conversation is about to end. Say a short goodbye in one sentence." } }), Math.max(0, max - WRAP_UP_SECONDS * 1000));
      maxTimer = setTimeout(() => end("time"), max);
    } catch (e) {
      if (!stale()) { const code = e instanceof TalkError ? e.code : "error"; end(code === "error" ? "error" : code, e.message, e instanceof TalkError ? { resetsAt: e.resetsAt, scope: e.scope } : {}); if (e instanceof TalkError) o.onError({ code: e.code, message: e.message }); }
    }
  }

  return {
    start,
    stop: () => end("stopped"),
    // ask the guide, in words, to sound different from now on (pace, tone, accent); best effort, nothing happens when not talking
    nudge: (text) => { if (ws && ws.readyState === 1 && ready && !ending && text) ws.send(JSON.stringify({ realtimeInput: { text: String(text).slice(0, 300) } })); },
    skipIntro: () => { try { introWake?.(); introStop?.(); interrupt(); } catch { /* done */ } },
    setMuted: (m) => {
      muted = !!m;
      if (muted && ws && ws.readyState === 1) ws.send(JSON.stringify({ realtimeInput: { audioStreamEnd: true } }));   // flush what was heard
    },
    get state() { return state; },
  };
}
