// "Talk to the article": the browser side of a live voice conversation (owner, Oct 11 2026). No design in here: the
// site gives it callbacks and draws whatever it likes. No dependencies; one ES module.
//
//   const talk = createTalk({
//     tokenUrl: `${SUPABASE_URL}/functions/v1/live-token`,
//     getHeaders: async () => ({ apikey: SUPABASE_KEY, Authorization: `Bearer ${await token()}` }),
//     introBase: "/live/",                      // intro.json, intro-en.m4a, intro-hi.m4a (nishpaksh/live_intro.py)
//     onState: (s) => ..., onHighlight: (id) => ..., onTranscript: (lines) => ..., onLevel: (rms) => ...,
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

// -- the protocol (pure) --------------------------------------------------------------------------------------

const HIGHLIGHT = {
  name: "highlight",
  description: "Light up the article sentence you are about to talk about, so the reader sees it. Call it before you speak about a sentence, with its id (the text in square brackets, for example p2s0). Never say the id aloud.",
  parameters: { type: "OBJECT", properties: { sentence_id: { type: "STRING", description: "The sentence id, for example p2s0" } }, required: ["sentence_id"] },
};

/** The first message on the socket. `instruction` comes from the live-token function (the same text its token is locked
 *  to). `nested`: put responseModalities and speechConfig under generationConfig (the older layout) if the server
 *  rejects the flat one. */
export function setupMessage({ model, instruction, voice = "Kore", languageCode = null, nested = false }) {
  const speech = { voiceConfig: { prebuiltVoiceConfig: { voiceName: voice } } };
  if (languageCode) speech.languageCode = languageCode;     // only when the function sends one (off by default: native-audio models pick the language themselves)
  const setup = {
    model: `models/${model}`,
    systemInstruction: { parts: [{ text: instruction }] },
    inputAudioTranscription: {},
    outputAudioTranscription: {},
    tools: [{ functionDeclarations: [HIGHLIGHT] }],
    // 500-800 ms of silence ends the reader's turn (Google's guidance: shorter splits a sentence at a breath)
    realtimeInputConfig: { automaticActivityDetection: { silenceDurationMs: 700, prefixPaddingMs: 100 } },
  };
  if (nested) setup.generationConfig = { responseModalities: ["AUDIO"], speechConfig: speech };
  else { setup.responseModalities = ["AUDIO"]; setup.speechConfig = speech; }
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
  constructor(code, message) { super(message || code); this.code = code; }
}

// -- the controller (needs a browser) -------------------------------------------------------------------------

export function createTalk(opts) {
  const o = { introBase: "./", onState() {}, onHighlight() {}, onTranscript() {}, onLevel() {}, onEnd() {}, onError() {}, ...opts };
  let state = "idle", ctx = null, stream = null, ws = null, proto = null, grant = null;
  let tapNode = null, tapSource = null, silent = null, muted = false, micOn = false, ending = false;
  let introDone = false, ready = false, introStop = null;
  let nextAt = 0, quietTimer = null, idleTimer = null, maxTimer = null, wrapTimer = null, lastActive = 0;
  const playing = new Set();
  let runId = 0;                 // each start() is a run; stop() during connecting must stop THAT run from carrying on

  const set = (s) => { if (state !== s) { state = s; o.onState(s); } };
  const touch = () => { lastActive = Date.now(); };

  // playback: each chunk of the guide's voice is queued right after the one before
  function playPcm(int16) {
    if (!ctx || ending) return;
    touch();
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
    const onChunk = (f32) => {
      if (muted || !ws || ws.readyState !== 1) return;
      const level = rms(f32);
      o.onLevel(level);
      if (level > 0.02) touch();
      ws.send(JSON.stringify({ realtimeInput: { audio: { data: int16ToBase64(floatTo16kPcm(f32, ctx.sampleRate)), mimeType: `audio/pcm;rate=${IN_RATE}` } } }));
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
    throw new TalkError(code, j.error || `HTTP ${r.status}`);
  }

  // the fixed intro: a recording when there is one, the browser's own voice when not (so it works before the clips exist)
  async function playIntro(lang) {
    let text = null, buffer = null;
    try { text = await (await fetch(`${o.introBase}intro.json`)).json(); } catch { /* none */ }
    try {
      const r = await fetch(`${o.introBase}intro-${lang}.m4a`);
      if (r.ok) buffer = await ctx.decodeAudioData(await r.arrayBuffer());
    } catch { /* no clip */ }
    if (ending) return;
    set("intro");
    if (buffer) {
      await new Promise((resolve) => {
        const src = ctx.createBufferSource();
        src.buffer = buffer;
        src.connect(ctx.destination);
        introStop = () => { try { src.onended = null; src.stop(); } catch { /* done */ } resolve(); };
        src.onended = resolve;
        src.start();
      });
    } else if (text?.[lang] && typeof speechSynthesis !== "undefined") {
      for (let i = 0; i < text[lang].length && !ending; i++) {
        if (i) await new Promise((r) => setTimeout(r, (text.pause_seconds || 0.9) * 1000));
        await new Promise((resolve) => {
          const u = new SpeechSynthesisUtterance(text[lang][i]);
          u.lang = lang === "hi" ? "hi-IN" : "en-IN";
          u.onend = resolve; u.onerror = resolve;
          introStop = () => { speechSynthesis.cancel(); resolve(); };
          speechSynthesis.speak(u);
        });
      }
    }
    introStop = null;
  }

  function openSocket() {
    ws = new WebSocket(`${WS_URL}?access_token=${encodeURIComponent(grant.token)}`);
    proto = new LiveProtocol({
      sentenceIds: grant.sentence_ids,
      send: (m) => ws && ws.readyState === 1 && ws.send(JSON.stringify(m)),
      on: {
        ready: () => { ready = true; maybeOpenMic(); },
        audio: playPcm,
        interrupted: interrupt,
        turnComplete: touch,
        highlight: (id) => { touch(); o.onHighlight(id); },
        transcript: (lines) => { touch(); o.onTranscript(lines); },
        goAway: () => end("goaway"),
      },
    });
    ws.onopen = () => ws.send(JSON.stringify(setupMessage({ model: grant.model, instruction: grant.instruction, voice: grant.voice || undefined, languageCode: grant.language_code || null })));
    ws.onmessage = async (e) => {
      try { proto.handle(JSON.parse(typeof e.data === "string" ? e.data : await e.data.text())); }
      catch { /* one bad frame does not end the conversation */ }
    };
    ws.onerror = () => {};
    ws.onclose = (e) => { if (!ending) end(ready ? "closed" : "refused", `${e.code} ${e.reason || ""}`.trim()); };
  }

  function end(reason, detail) {
    if (ending) return;
    ending = true;
    clearTimeout(quietTimer); clearInterval(idleTimer); clearTimeout(maxTimer); clearTimeout(wrapTimer);
    try { introStop?.(); } catch { /* done */ }
    try { for (const s of playing) { s.onended = null; s.stop(); } } catch { /* done */ }
    playing.clear();
    try { ws && ws.readyState <= 1 && ws.close(1000); } catch { /* done */ }
    try { tapNode && (tapNode.port ? (tapNode.port.onmessage = null) : (tapNode.onaudioprocess = null)); tapNode?.disconnect(); tapSource?.disconnect(); } catch { /* done */ }
    try { stream?.getTracks().forEach((t) => t.stop()); } catch { /* done */ }
    try { ctx && ctx.state !== "closed" && ctx.close(); } catch { /* done */ }
    set("ended");
    if (reason === "refused" || reason === "error") o.onError({ code: reason, message: detail || reason });
    o.onEnd({ reason, detail });
  }

  async function start({ storyId, lang, style }) {
    if (state !== "idle" && state !== "ended") return;
    ending = false; muted = false; micOn = false; introDone = false; ready = false; nextAt = 0;
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
      if (o.onGrant) o.onGrant({ lang, headline: grant.headline, instruction: grant.instruction, sentenceIds: grant.sentence_ids, maxSeconds: grant.max_seconds, daily: grant.daily });
      openSocket();
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
      if (!stale()) { const code = e instanceof TalkError ? e.code : "error"; end(code === "error" ? "error" : code, e.message); if (e instanceof TalkError) o.onError({ code: e.code, message: e.message }); }
    }
  }

  return {
    start,
    stop: () => end("stopped"),
    // ask the guide, in words, to sound different from now on (pace, tone, accent); best effort, nothing happens when not talking
    nudge: (text) => { if (ws && ws.readyState === 1 && ready && !ending && text) ws.send(JSON.stringify({ realtimeInput: { text: String(text).slice(0, 300) } })); },
    skipIntro: () => { try { introStop?.(); } catch { /* done */ } },
    setMuted: (m) => {
      muted = !!m;
      if (muted && ws && ws.readyState === 1) ws.send(JSON.stringify({ realtimeInput: { audioStreamEnd: true } }));   // flush what was heard
    },
    get state() { return state; },
  };
}
