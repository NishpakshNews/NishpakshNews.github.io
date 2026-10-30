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
//     onArticle: ({id, headline}) => ...,       // the guide opened another article (a function call it makes by itself); the page may say "Reading: <headline>"
//     onGrant: ({instruction, sentenceIds, maxSeconds, daily}) => ...,   // what the guide was given (for testing)
//     onEnd: ({reason}) => ..., onError: ({code, message}) => ...,
//   });
//   await talk.start({ storyId, lang, style });  // (a conversation about the DAY'S RECAP: start({ recap: "2026-10-12", lang, style }), owner Oct 12 2026)  // style: {voice, pace, tone, accent}, all optional (the function checks them)
//   talk.nudge("From now on, speak slowly.");  // asks the guide to sound different mid-conversation        // from a tap: the browser asks for the microphone then
//   talk.skipIntro(); talk.setMuted(true); talk.stop();
//
// What happens: the intro recording of the reader's chosen voice starts AT ONCE on the tap (intro-<voice>-<lang>.m4a, see
// nishpaksh/live_intro.py) while microphone permission -> the live-token function (login, limits, the article's brief, a
// one-use Gemini token) -> the WebSocket all happen behind it; without that recording the guide says the intro itself once
// the socket is ready (slower: several seconds of nothing) -> the microphone opens -> the reader talks and can
// interrupt at any time (Gemini detects speech; this module stops its own playback the moment the server says
// "interrupted"). States: idle, connecting, intro, listening, speaking, ended.
//
// Gemini's Live API: https://ai.google.dev/gemini-api/docs/live-api/get-started-websocket (audio in: 16 kHz 16-bit
// PCM; out: 24 kHz). The pure parts (audio conversion, message handling) are exported and tested in node
// (tests/live/talk.test.mjs); the part that needs a browser (microphone, speakers, socket) is `createTalk`.

export const WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained";
export const IN_RATE = 16000;
export const OUT_RATE = 24000;
const CLIP_RATE = { slow: 0.85, natural: 1, fast: 1.15 };   // the recording is one file per voice, so the reader's pace choice is applied to it as its playback speed (owner, Oct 12 2026)
const CLIP_LEAD_S = 1.2;                // the recording is scheduled this far ahead of "now" (owner, Oct 12 2026: heard from mid-clip, while a screen recording had it from the first word): opening the microphone makes the phone / Bluetooth / laptop re-route its audio, and until that settles the speaker swallows what it is given. The clips start with ~0.2 s of near-silence, so the first WORDS still land after the device is awake
const FILLERS = 4;                      // filler-<Voice>-<lang>-1..4.m4a (nishpaksh/live_intro.py, live/intro.json filler_en / filler_hi): a short line played while the guide opens another article
const CLIP_WAIT_MS = 4000;              // the intro recording must have started within this long after the connection is ready, else the guide says the intro itself
const INTRO_WAIT_MS = 15000;            // how long the intro waits for the server to be ready
const INTRO_MAX_MS = 30000;             // and for the guide to finish saying it
const THINK_AFTER_MS = 500;            // the reader's voice has been quiet this long: their turn is over, the guide is working on its answer
const THINK_MAX_MS = 60000;            // "thinking" never lasts longer than this (the guide may simply have had nothing to say). It was 20 s: a big question takes longer, and the page then looked as if nothing was happening
const TOOL_STALL_MS = 1800;            // the guide was answered about a highlight and has said nothing since: it is waiting, so it is told to go on (see the watchdog)
const NO_ANSWER_MS = 7000;             // the reader finished and nothing at all came back (the end of their turn was not noticed): the guide is told to go on
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

/** 24 kHz guide audio -> the AudioContext's own rate, chunk after chunk WITHOUT seams (owner, Oct 11 2026: random loud beeps while talking).
 *  Before, every chunk was handed to the browser as its own 24 kHz buffer on a 44.1/48 kHz context: each buffer was resampled alone and
 *  its start rounded to a frame, which leaves a step (a click or a short beep) at the joint of two chunks. This keeps its place (the
 *  fractional position and the last sample) between calls, so the chunks join as one continuous wave. */
export class Resampler {
  constructor(inRate, outRate) { this.step = inRate / outRate; this.same = inRate === outRate; this.reset(); }
  reset() { this.pos = 0; this.last = 0; }
  process(f) {
    if (this.same || !f.length) return f;
    const n = f.length;
    const out = new Float32Array(Math.ceil((n - this.pos) / this.step) + 2);
    let pos = this.pos, k = 0;
    for (;;) {
      const i = Math.floor(pos);
      if (i + 1 >= n) break;                                 // the next input sample is in the next chunk: wait for it
      const a = i < 0 ? this.last : f[i];
      out[k++] = a + (f[i + 1] - a) * (pos - i);
      pos += this.step;
    }
    this.pos = pos - n;                                      // where the next chunk starts, counted from ITS first sample
    this.last = f[n - 1];
    return out.subarray(0, k);
  }
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
  constructor({ sentenceIds, send, on, nonBlocking = false }) {
    this.nonBlocking = !!nonBlocking;       // only a function declared NON_BLOCKING may be answered SILENT; for any other the answer must let the model carry on
    this.ids = new Set(sentenceIds || []);
    this.send = send;
    this.on = on || {};
    this.lines = [];            // the conversation so far: {role: "you" | "guide", text, open, segments?}
  }

  validId(id) {
    const s = String(id || "").trim();
    return this.ids.has(s) || this.ids.has(s.split(".")[0]) ? s : null;
  }

  _said(role, text, timing = null) {
    if (!text) return;
    const last = this.lines[this.lines.length - 1];
    let line, startIndex;
    if (last && last.role === role && last.open) {
      line = last; startIndex = last.text.length; last.text += text;
    } else {
      line = { role, text, open: true, id: this.lines.length }; startIndex = 0; this.lines.push(line);
    }
    if (role === "guide") {
      line.segments ||= [];
      line.segments.push({
        text, startIndex, endIndex: startIndex + text.length,
        startOffset: timing?.startOffset ?? null, endOffset: timing?.endOffset ?? null,
      });
    }
    const latestGuide = [...this.lines].reverse().find((l) => l.role === "guide");
    // Keep the long-standing public transcript shape unchanged; timings travel as a second callback argument.
    this.on.transcript?.(
      this.lines.map((l) => ({ role: l.role, text: l.text })),
      { lineId: latestGuide?.id ?? null, segments: latestGuide?.segments ? latestGuide.segments.map((seg) => ({ ...seg })) : [] },
    );
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
      if (sc.outputTranscription?.text) this._said("guide", sc.outputTranscription.text, sc.outputTranscription);
      if (sc.interrupted) { this._closeLines(); this.on.interrupted?.(); }
      if (sc.turnComplete) { this._closeLines(); this.on.turnComplete?.(); }
    }
    if (msg.toolCall) this._tools(msg.toolCall.functionCalls || []);
    if (msg.goAway) this.on.goAway?.(msg.goAway.timeLeft);
  }

  _tools(calls) {
    const responses = [];
    const pending = [];
    for (const fc of calls) {
      this.on.tool?.(fc.name);
      if (fc.name === "open_article") {
        // The answer is the article's text, fetched by the page while the guide waits (an ordinary function, never SILENT: the guide
        // must carry on when the text arrives). A failure is told to the guide in words, so it answers from what it has instead of freezing.
        pending.push(Promise.resolve().then(() => this.on.open?.(fc.args?.story_id)).catch(() => null).then((r) => ({
          id: fc.id, name: fc.name,
          response: r && r.ok && r.text ? { article: r.text } : { error: "That article could not be opened. Answer from what you already have, and say you could not open the full article." },
        })));
        continue;
      }
      let result = "unknown function";
      if (fc.name === "highlight") {
        const id = this.validId(fc.args?.sentence_id);
        if (id) { this.on.highlight?.(id); result = "ok"; } else result = "no such sentence id";
      }
      // SILENT means "write this into the conversation but do NOT generate": right for a non-blocking function (the model is already talking),
      // WRONG for an ordinary one, where the model has stopped to wait for this answer and then never carries on until the reader speaks again
      // (the guide went quiet for 10+ seconds after a highlight, owner, Oct 11 2026). So it is only sent for a function declared NON_BLOCKING.
      responses.push(this.nonBlocking ? { id: fc.id, name: fc.name, response: { result }, scheduling: "SILENT" } : { id: fc.id, name: fc.name, response: { result } });
    }
    if (responses.length) { this.send({ toolResponse: { functionResponses: responses } }); this.on.toolReplied?.(); }
    if (pending.length) Promise.all(pending).then((rs) => { this.send({ toolResponse: { functionResponses: rs } }); this.on.toolReplied?.(); });
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
  const o = { introBase: "./", onState() {}, onHighlight() {}, onTranscript() {}, onTurnComplete() {}, onLevel() {}, onEnd() {}, onError() {}, ...opts };
  let state = "idle", ctx = null, stream = null, ws = null, proto = null, grant = null, outRs = null;
  let tapNode = null, tapSource = null, silent = null, muted = false, micOn = false, ending = false;
  let thinkTimer = null, voiced = false, lastVoice = 0, thinkSince = 0, pingTimer = null, introDone = false, ready = false, introStop = null, introWake = null, readyWake = null;
  let wsOpenAt = 0;
  let toolReplyAt = 0, silentAt = 0, nudged = false;   // the watchdog: when a function call was last answered, when the guide last ended a turn without a sound, and whether this question was already pushed once
  let askEnd = 0, firstTool = 0, toolCount = 0;      // timing of one answer: when the reader stopped, when the guide first called a function, when its voice began
  let turnStart = 0, turnTotal = 0, turnOffset = 0, turnId = 0, turnClockActive = false, turnCompleteSeen = false;
  // The audio clock is continuous across short gaps in one answer, and gets a new id for the next answer.
  let nextAt = 0, quietTimer = null, idleTimer = null, maxTimer = null, wrapTimer = null, lastActive = 0, slow = false;
  const playing = new Set();
  const clipBytes = new Map();   // intro recordings already asked for: name -> Promise of its bytes (or null)
  let openPending = 0, curVoice = null, curLang = "en", lastFiller = 0;   // articles being fetched for the guide, the voice and language of this conversation, the filler played last
  const opened = new Map();      // story id -> the article's answer (a promise); an article is fetched once per conversation
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
    if (askEnd || turnCompleteSeen) {
      turnStart = 0; turnTotal = 0; turnOffset = 0; turnClockActive = false; turnCompleteSeen = false;
    }
    if (askEnd) {           // the first sound of an answer: how long after the reader stopped (this includes the ~1 s of waiting for the end of their turn)
      const now = Date.now();
      o.onMetric?.({ firstAudioMs: now - askEnd, firstToolMs: firstTool ? firstTool - askEnd : null, tools: toolCount });
      askEnd = 0; firstTool = 0; toolCount = 0;
    }
    if (!outRs) outRs = new Resampler(OUT_RATE, ctx.sampleRate);
    const f = outRs.process(pcm16ToFloat32(int16));
    if (!f.length) return;
    const at = Math.max(ctx.currentTime + 0.02, nextAt);
    if (!turnClockActive) { turnId++; turnClockActive = true; turnStart = at; turnTotal = 0; turnOffset = 0; }
    if (!playing.size && at > nextAt + 1e-4) { turnOffset += turnTotal; turnStart = at; turnTotal = 0; } // preserve the answer timeline across short playback gaps
    if (at > nextAt + 1e-4) {                                // a new stretch of speech (not the next chunk of one): 3 ms fade-in, so it does not start with a click
      const m = Math.min(f.length, Math.floor(ctx.sampleRate * 0.003));
      for (let i = 0; i < m; i++) f[i] *= i / m;
    }
    const buf = ctx.createBuffer(1, f.length, ctx.sampleRate);
    buf.copyToChannel(f, 0);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    src.start(at);
    nextAt = at + buf.duration;
    turnTotal += buf.duration;
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
    nextAt = 0; turnStart = 0; turnTotal = 0; turnOffset = 0; turnClockActive = false; turnCompleteSeen = false;
    outRs?.reset();
    if (micOn && !ending) set("listening");
  }

  // The reader's question has been heard but nothing has come back. Saying "go ahead and tell me now" always made the guide answer at once, so
  // when the guide is stuck the page says that for the reader, once per question. Stuck means: (1) it was answered about a highlight and stayed
  // quiet, or (2) nothing at all came back for NO_ANSWER_MS and the guide did not end a turn (the end of the reader's turn was not noticed).
  // A guide that ended a turn without a sound and without a function call had nothing to say (noise): that is left alone.
  function watchdog(now) {
    if (!askEnd || nudged || !ready || ending || openPending || playing.size || !ws || ws.readyState !== 1) return;
    const afterTool = toolReplyAt > askEnd && now - toolReplyAt > TOOL_STALL_MS;
    const noAnswer = silentAt <= askEnd && now - askEnd > NO_ANSWER_MS;
    if (!afterTool && !noAnswer) return;
    nudged = true;
    o.onMetric?.({ nudged: afterTool ? "after-highlight" : "no-answer", afterMs: now - askEnd });
    proto.send({ realtimeInput: { text: "Go ahead and answer now." } });
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
      if (state === "listening" && voiced && !playing.size && now - lastVoice > THINK_AFTER_MS) { voiced = false; thinkSince = now; askEnd = lastVoice; firstTool = 0; toolCount = 0; nudged = false; set("thinking"); }
      else if (state === "thinking") {
        touch();                                                   // waiting for the guide is not "nobody is speaking": the 45 s idle end must not fire while it works
        if (!slow && now - thinkSince > SLOW_AFTER_MS) { slow = true; o.onSlow?.(true); }
        if (now - thinkSince > THINK_MAX_MS) set("listening");
      }
      watchdog(now);
    }, 150);
  }

  function maybeOpenMic() { if (introDone && ready && !ending) startMic(); }

  async function grantFor(storyId, lang, style, recap) {
    let r;
    const t0 = Date.now();
    try {
      r = await fetch(o.tokenUrl, { method: "POST", headers: { "Content-Type": "application/json", ...(await o.getHeaders()) }, body: JSON.stringify(recap ? { recap, lang, style } : { story_id: storyId, lang, style }) });
    } catch { throw new TalkError("network", "could not reach Nishpaksh"); }
    let j = {};
    try { j = await r.json(); } catch { /* no body */ }
    if (r.ok && j.token) { o.onMetric?.({ grantMs: Date.now() - t0, server: j.timing || null }); return j; }
    const code = r.status === 401 ? "login" : r.status === 429 ? "limit" : r.status === 503 && j.error === "busy" ? "busy" : r.status === 404 ? "gone" : "unavailable";
    throw new TalkError(code, j.error || `HTTP ${r.status}`, code === "limit" ? { resetsAt: j.resets_at || null, scope: j.scope || "hour" } : {});
  }


  // The intro recording (owner, Oct 11 2026: "the card is instant but the voice comes after a long time"). It is one file per voice and language,
  // so it sounds like the guide the reader picked; it is fetched before the tap when the page asks (preload) and starts the moment the tap's
  // audio context is running, while everything else (microphone, login, token, socket) is still going on behind it.
  // The recap's guide has its own words ("what would you like to know about today's news?"), so its recordings are named intro-recap-<voice>-<lang>.m4a
  // (a voice without one is simply said by the guide itself, as for any missing recording).
  const clipName = (voice, lang, kind) => `intro-${kind === "recap" ? "recap-" : ""}${safeVoice(voice)}-${lang === "hi" ? "hi" : "en"}.m4a`;
  const fillerName = (voice, lang, n) => `filler-${safeVoice(voice)}-${lang === "hi" ? "hi" : "en"}-${n}.m4a`;
  const safeVoice = (v) => (typeof v === "string" && /^[A-Za-z]{2,20}$/.test(v) ? v : "Kore");
  function fetchClip(name) {
    if (!clipBytes.has(name)) clipBytes.set(name, (async () => {
      try { const r = await fetch(`${o.introBase}${name}`); return r.ok ? await r.arrayBuffer() : null; } catch { return null; }
    })());
    return clipBytes.get(name);
  }
  /** Wake the token function before the reader taps (its first call after a quiet spell took 5 s: 2 s to start, 3.6 s of work). Best effort. */
  function warm() {
    Promise.resolve(o.getHeaders()).then((h) => fetch(o.tokenUrl, { method: "POST", headers: { "Content-Type": "application/json", ...h }, body: JSON.stringify({ warm: 1 }) })).catch(() => {});
  }
  /** Start fetching the recording early (the page calls this before the reader taps), so the tap only has to play it. */
  function preload({ lang = "en", voice, kind } = {}) { fetchClip(clipName(voice, lang, kind)); }
  // The guide called open_article. A recorded filler line covers the wait ("let me pull that up"), queued so the guide's own answer
  // starts right after it; the article's text is fetched from the same function (no login check, no count) and kept for the conversation.
  async function playFiller() {
    if (!ctx || ending) return;
    let n = 1 + Math.floor(Math.random() * FILLERS);
    if (n === lastFiller) n = (n % FILLERS) + 1;                 // never the same line twice in a row
    lastFiller = n;
    const bytes = await fetchClip(fillerName(curVoice, curLang, n));
    if (!bytes || !ctx || ending) return;                        // no recording for this voice: silence until the answer (it is quick)
    try {
      const buf = await ctx.decodeAudioData(bytes.slice(0));
      if (!ctx || ending) return;
      if (ctx.state !== "running") { try { await ctx.resume(); } catch { /* played or not below */ } }
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      const at = Math.max(ctx.currentTime + 0.02, nextAt);
      src.start(at);
      nextAt = at + buf.duration;
      playing.add(src);
      touch(); set("speaking");
      src.onended = () => {
        playing.delete(src);
        clearTimeout(quietTimer);
        quietTimer = setTimeout(() => { if (!playing.size && !ending && micOn) set("listening"); }, 250);
      };
    } catch { /* the guide's answer follows anyway */ }
  }
  async function openArticle(raw) {
    const id = Math.floor(Number(String(raw ?? "").replace(/^[as]/i, "")));
    if (!Number.isInteger(id) || id < 1 || ending) return { ok: false };
    const t0 = Date.now(), cached = opened.has(id);
    if (!cached) {
      playFiller();
      opened.set(id, (async () => {
        try {
          const r = await fetch(o.tokenUrl, { method: "POST", headers: { "Content-Type": "application/json", ...(await o.getHeaders()) }, body: JSON.stringify({ open: id, lang: curLang }), signal: AbortSignal.timeout(8000) });
          const j = await r.json().catch(() => ({}));
          return r.ok && j.ok && j.text ? j : { ok: false };
        } catch { return { ok: false }; }
      })());
    }
    openPending++;
    let r;
    try { r = await opened.get(id); } finally { openPending--; }
    if (!r.ok) opened.delete(id);                                // a failed one may be tried again
    else if (!cached) o.onArticle?.({ id, headline: r.headline });
    touch();
    o.onMetric?.({ openMs: Date.now() - t0, openedId: id, ok: !!r.ok, cached });
    return r;
  }
  /** Begins the recording as soon as it is decoded. `started` resolves true (playing, `seconds` long) or false (none, or it could not be played). */
  function startClip(lang, voice, after = Promise.resolve(), kind = "article", pace = "natural") {
    const run = { cancelled: false, seconds: 0 };
    run.started = (async () => {
      const bytes = await fetchClip(clipName(voice, lang, kind));
      if (!bytes || run.cancelled || ending || !ctx) return false;
      try {
        const buf = await ctx.decodeAudioData(bytes.slice(0));     // decoded NOW, while the microphone is being asked for
        await after;                                               // ... but played once the microphone is open: opening it re-routes the phone's audio (Bluetooth most of all) and cut off the first words
        if (run.cancelled || ending || !ctx) return false;
        if (ctx.state !== "running") { try { await ctx.resume(); } catch { /* played or not below */ } }   // the permission box can pause the context
        if (run.cancelled || ending || !ctx) return false;
        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.connect(ctx.destination);
        const rate = CLIP_RATE[pace] || 1;
        src.playbackRate.value = rate;
        const at = Math.max(ctx.currentTime + CLIP_LEAD_S, nextAt);
        src.start(at);
        nextAt = at + buf.duration / rate;
        playing.add(src);
        run.seconds = buf.duration / rate;
        setTimeout(() => { if (!ending && playing.has(src)) set("intro"); }, Math.max(0, (at - ctx.currentTime) * 1000));   // "connecting" stays on the card until the voice is really heard (the first moments are the device waking up)
        return true;
      } catch { return false; }
    })();
    return run;
  }

  // The intro is spoken by the guide itself (owner, Oct 11 2026: the voice must match everywhere, whichever voice the
  // reader picked): once the server is ready, it is asked to say the fixed words (live/intro.json) and nothing else.
  // The microphone opens only after it has finished, so it never hears itself.
  const sleep = (ms, stopper) => new Promise((resolve) => {
    const t = setTimeout(resolve, ms);
    stopper(() => { clearTimeout(t); resolve(); });
  });
  async function playIntro(lang, kind = "article") {
    let text = null;
    try { text = await (await fetch(`${o.introBase}intro.json`)).json(); } catch { /* none */ }
    const words = (kind === "recap" && text?.[`recap_${lang}`]) || text?.[lang];
    if (ending || !Array.isArray(words) || words.length < 1) return;     // no words: the guide just waits for the reader
    set("intro");
    if (!ready) await sleep(INTRO_WAIT_MS, (stop) => { readyWake = stop; });
    readyWake = null;
    if (ending || !ready) return;
    const hindi = lang === "hi";
    proto.send({ realtimeInput: { text: `${hindi ? "In Hindi, say" : "Say"} this one sentence aloud now, exactly as written, and nothing else. Do not call any function. "${words.join(" ")}"` } });
    await sleep(INTRO_MAX_MS, (stop) => { introWake = stop; introStop = stop; });    // the end of the guide's turn
    introWake = null; introStop = null;
    if (ending) return;
    const left = (nextAt - ctx.currentTime) * 1000;                        // what is still queued to play
    if (left > 0) await sleep(left + 150, (stop) => { introStop = stop; });
    introStop = null;
  }

  function openSocket() {
    wsOpenAt = Date.now();
    ws = new WebSocket(`${WS_URL}?access_token=${encodeURIComponent(grant.token)}`);
    proto = new LiveProtocol({
      sentenceIds: grant.sentence_ids,
      send: (m) => ws && ws.readyState === 1 && ws.send(JSON.stringify(m)),
      nonBlocking: (grant.tools || []).some((t) => (t.functionDeclarations || []).some((d) => d.behavior === "NON_BLOCKING")),
      on: {
        ready: () => { ready = true; o.onMetric?.({ socketReadyMs: Date.now() - wsOpenAt }); readyWake?.(); maybeOpenMic(); },
        audio: playPcm,
        interrupted: interrupt,
        toolReplied: () => { toolReplyAt = Date.now(); },
        turnComplete: () => { touch(); turnCompleteSeen = true; if (askEnd) silentAt = Date.now(); introWake?.(); if (state === "thinking" && !playing.size) set("listening"); o.onTurnComplete(); },
        tool: () => { if (askEnd && !firstTool) firstTool = Date.now(); toolCount++; },
        highlight: (id) => { touch(); o.onHighlight(id); },
        open: openArticle,
        transcript: (lines, meta) => { touch(); o.onTranscript(lines, meta); },
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
    try { readyWake?.(); introWake?.(); } catch { /* done */ }   // a start still waiting for the server or for the intro returns now, not 15-30 s later
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

  async function start({ storyId, recap, lang, style }) {
    const kind = recap ? "recap" : "article";
    if (state !== "idle" && state !== "ended") return;
    ending = false; muted = false; micOn = false; voiced = false; introDone = false; ready = false; nextAt = 0
    const run = ++runId;
    const stale = () => ending || run !== runId;     // stopped (or restarted) while this run was waiting on something
    set("connecting");
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      ctx = new AC();
      outRs = null;                        // made on the first chunk, for this context's rate
      await ctx.resume();                  // inside the reader's tap, so the browser lets it play
      if (stale()) return;
      let micOpened; const micAsked = new Promise((r) => { micOpened = r; });
      const clip = startClip(lang, style?.voice, micAsked, kind, style?.pace);   // the recording is made ready now and plays the moment the microphone is open, before the login and the socket
      let mic;
      try {
        mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
      } catch { micOpened(); throw new TalkError("mic", "the microphone is blocked"); }
      micOpened();
      if (stale()) { try { mic.getTracks().forEach((t) => t.stop()); } catch { /* done */ } return; }   // never leave a microphone open
      stream = mic;
      grant = await grantFor(storyId, lang, style, recap);
      if (stale()) return;
      lang = grant.lang || lang;
      curLang = lang; curVoice = grant.voice || style?.voice || null; opened.clear(); openPending = 0;
      for (let n = 1; n <= FILLERS; n++) fetchClip(fillerName(curVoice, curLang, n));      // the filler lines are small: ready before the first article is opened
      if (o.onGrant) o.onGrant({ lang, headline: grant.headline, instruction: grant.instruction, sentenceIds: grant.sentence_ids, maxSeconds: grant.max_seconds, hourly: grant.hourly });
      openSocket();
      startPings();
      const played = await Promise.race([clip.started, new Promise((r) => setTimeout(() => r(false), CLIP_WAIT_MS))]);
      if (!played) clip.cancelled = true;              // too late (or none): the guide says the intro itself, and the recording must not start on top of it
      if (stale()) return;
      if (played) {
        const left = Math.max(0, (nextAt - ctx.currentTime) * 1000);          // what is still to play of the recording
        if (left > 0) await sleep(left + 150, (stop) => { introStop = stop; });
        introStop = null;
      } else await playIntro(lang, kind);
      if (stale()) return;
      introDone = true;
      maybeOpenMic();
      touch();
      idleTimer = setInterval(() => { if (!muted && Date.now() - lastActive > IDLE_SECONDS * 1000) end("idle"); }, 2000);     // a muted reader is not "gone quiet": the 8-minute limit still ends it
      const max = (grant.max_seconds || 480) * 1000;
      wrapTimer = setTimeout(() => proto?.send({ realtimeInput: { text: "The conversation is about to end. Say a short goodbye in one sentence." } }), Math.max(0, max - WRAP_UP_SECONDS * 1000));
      maxTimer = setTimeout(() => end("time"), max);
    } catch (e) {
      if (!stale()) { const code = e instanceof TalkError ? e.code : "error"; end(code === "error" ? "error" : code, e.message, e instanceof TalkError ? { resetsAt: e.resetsAt, scope: e.scope } : {}); if (e instanceof TalkError) o.onError({ code: e.code, message: e.message }); }
    }
  }

  return {
    start,
    preload,
    warm,
    stop: () => end("stopped"),
    // ask the guide, in words, to sound different from now on (pace, tone, accent); best effort, nothing happens when not talking
    nudge: (text) => { if (ws && ws.readyState === 1 && ready && !ending && text) ws.send(JSON.stringify({ realtimeInput: { text: String(text).slice(0, 300) } })); },
    skipIntro: () => { try { introWake?.(); introStop?.(); interrupt(); } catch { /* done */ } },
    setMuted: (m) => {
      muted = !!m;
      if (!muted) touch();                // unmuting is activity: the idle clock starts again
      if (muted && ws && ws.readyState === 1) ws.send(JSON.stringify({ realtimeInput: { audioStreamEnd: true } }));   // flush what was heard
    },
    // how much of the guide's current speech has been HEARD so far, 0..1 (1 when nothing is playing): the captions follow it so the words keep the pace of the voice
    pace: () => {
      if (!ctx || !turnTotal || !playing.size) return 1;
      return Math.max(0, Math.min(1, (ctx.currentTime - turnStart) / turnTotal));
    },
    // where the guide's voice is, in seconds of its current speech: `at` heard so far, `total` queued so far (null when nothing is playing);
    // the captions give every word its moment on this clock, so the text follows what is HEARD
    clock: () => {
      // Local intro recordings share `playing` but do not have a generated-transcript audio clock.
      // Return a stable position during gaps so captions hold, rather than fast-forwarding or resetting.
      if (!ctx || !turnClockActive || !turnTotal) return null;
      const localAt = Math.max(0, Math.min(turnTotal, ctx.currentTime - turnStart));
      return { at: turnOffset + localAt, total: turnOffset + turnTotal, turnId, playing: playing.size > 0 };
    },
    get state() { return state; },
  };
}
