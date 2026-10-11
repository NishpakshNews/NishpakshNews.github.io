// node --test tests/live
import test from "node:test";
import assert from "node:assert/strict";
import { LiveProtocol, setupMessage, floatTo16kPcm, pcm16ToFloat32, int16ToBase64, base64ToInt16, rms, createTalk, IN_RATE, NoiseGate } from "../../live/talk.js";

test("the module loads in a plain runtime and only touches the browser when started", () => {
  const t = createTalk({ tokenUrl: "x", getHeaders: async () => ({}) });
  assert.equal(t.state, "idle");
});

test("audio from a 48 kHz microphone becomes 16 kHz, a third as many samples", () => {
  const f = new Float32Array(4800).fill(0.5);
  const out = floatTo16kPcm(f, 48000);
  assert.equal(out.length, 1600);
  assert.ok(out.every((v) => v === Math.round(0.5 * 0x7fff)));
});

test("audio already at 16 kHz is not resampled; loud audio is clipped, not wrapped", () => {
  const out = floatTo16kPcm(Float32Array.of(0, 1.5, -1.5, 0.25), IN_RATE);
  assert.deepEqual(Array.from(out), [0, 32767, -32768, Math.round(0.25 * 0x7fff)]);
});

test("a ramp keeps its shape through downsampling (averaging, not skipping)", () => {
  const f = Float32Array.from({ length: 480 }, (_, i) => i / 480);
  const out = floatTo16kPcm(f, 48000);
  assert.equal(out.length, 160);
  for (let i = 1; i < out.length; i++) assert.ok(out[i] > out[i - 1]);
});

test("base64 round trip is exact and little-endian", () => {
  const a = Int16Array.of(0, 1, -1, 32767, -32768, 12345, -12345);
  assert.deepEqual(Array.from(base64ToInt16(int16ToBase64(a))), Array.from(a));
  assert.equal(int16ToBase64(Int16Array.of(1)), btoa("\x01\x00"));
});

test("a big chunk encodes without blowing the stack", () => {
  const a = new Int16Array(160000).map((_, i) => (i % 2000) - 1000);
  assert.deepEqual(Array.from(base64ToInt16(int16ToBase64(a)).subarray(0, 50)), Array.from(a.subarray(0, 50)));
});

test("pcm to float stays within -1..1; rms of silence is 0", () => {
  const f = pcm16ToFloat32(Int16Array.of(-32768, 0, 32767));
  assert.deepEqual(Array.from(f), [-1, 0, 1]);
  assert.equal(rms(new Float32Array(10)), 0);
  assert.ok(Math.abs(rms(Float32Array.of(1, -1, 1, -1)) - 1) < 1e-9);
});

test("setup message: flat layout by default, nested on request, the instruction and the one tool in both", () => {
  const flat = setupMessage({ model: "gemini-3.8-live", instruction: "RULES" }).setup;
  assert.equal(flat.model, "models/gemini-3.8-live");
  assert.deepEqual(flat.responseModalities, ["AUDIO"]);
  assert.equal(flat.systemInstruction.parts[0].text, "RULES");
  assert.equal(flat.tools[0].functionDeclarations[0].name, "highlight");
  assert.deepEqual(flat.inputAudioTranscription, {});
  assert.equal(flat.speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName, "Kore");
  const nested = setupMessage({ model: "m", instruction: "R", nested: true }).setup;
  assert.equal(nested.responseModalities, undefined);
  assert.deepEqual(nested.generationConfig.responseModalities, ["AUDIO"]);
});

function proto(ids = ["p0s0", "p1s0.0", "p1s0.1"]) {
  const log = { sent: [], audio: [], hl: [], tr: [], events: [] };
  const p = new LiveProtocol({
    sentenceIds: ids,
    send: (m) => log.sent.push(m),
    on: {
      ready: () => log.events.push("ready"), audio: (a) => log.audio.push(a), interrupted: () => log.events.push("interrupted"),
      turnComplete: () => log.events.push("turn"), highlight: (id) => log.hl.push(id), transcript: (l) => log.tr.push(l),
      goAway: (t) => log.events.push(["goAway", t]),
    },
  });
  return { p, log };
}

test("setupComplete says ready", () => {
  const { p, log } = proto();
  p.handle({ setupComplete: {} });
  assert.deepEqual(log.events, ["ready"]);
});

test("model audio is decoded; a message with several parts gives all of them", () => {
  const { p, log } = proto();
  const a = int16ToBase64(Int16Array.of(1, 2, 3)), b = int16ToBase64(Int16Array.of(4, 5));
  p.handle({ serverContent: { modelTurn: { parts: [{ inlineData: { mimeType: "audio/pcm;rate=24000", data: a } }, { text: "ignored" }, { inlineData: { mimeType: "audio/pcm;rate=24000", data: b } }] } } });
  assert.deepEqual(log.audio.map((x) => Array.from(x)), [[1, 2, 3], [4, 5]]);
});

test("transcripts join into lines per speaker and close at the end of a turn", () => {
  const { p, log } = proto();
  p.handle({ serverContent: { inputTranscription: { text: "Is it " } } });
  p.handle({ serverContent: { inputTranscription: { text: "confirmed?" } } });
  p.handle({ serverContent: { outputTranscription: { text: "Only one outlet" } } });
  p.handle({ serverContent: { outputTranscription: { text: " reports it." }, turnComplete: true } });
  p.handle({ serverContent: { inputTranscription: { text: "Thanks" } } });
  assert.deepEqual(log.tr.at(-1), [
    { role: "you", text: "Is it confirmed?" }, { role: "guide", text: "Only one outlet reports it." }, { role: "you", text: "Thanks" },
  ]);
  assert.ok(log.events.includes("turn"));
});

test("interrupted is passed on and closes the guide's line, so the next words start a new one", () => {
  const { p, log } = proto();
  p.handle({ serverContent: { outputTranscription: { text: "The bridge" } } });
  p.handle({ serverContent: { interrupted: true } });
  p.handle({ serverContent: { outputTranscription: { text: "Sorry. Go on." } } });
  assert.deepEqual(log.events, ["interrupted"]);
  assert.deepEqual(log.tr.at(-1).map((l) => l.text), ["The bridge", "Sorry. Go on."]);
});

test("highlight: a real id lights up and is answered silently; a made-up id is ignored but answered", () => {
  const { p, log } = proto();
  p.handle({ toolCall: { functionCalls: [{ id: "a", name: "highlight", args: { sentence_id: "p0s0" } }, { id: "b", name: "highlight", args: { sentence_id: "p9s9" } }] } });
  assert.deepEqual(log.hl, ["p0s0"]);
  const r = log.sent[0].toolResponse.functionResponses;
  assert.deepEqual(r.map((x) => [x.id, x.response.result, x.scheduling]), [["a", "ok", "SILENT"], ["b", "no such sentence id", "SILENT"]]);
});

test("a part id lights up when the sentence has parts; the bare sentence id of a split sentence is not valid", () => {
  const { p, log } = proto();
  p.handle({ toolCall: { functionCalls: [{ id: "1", name: "highlight", args: { sentence_id: " p1s0.1 " } }, { id: "2", name: "highlight", args: { sentence_id: "p1s0" } }] } });
  assert.deepEqual(log.hl, ["p1s0.1"]);
});

test("an unknown function and a missing argument are answered, never thrown", () => {
  const { p, log } = proto();
  p.handle({ toolCall: { functionCalls: [{ id: "x", name: "launch", args: {} }, { id: "y", name: "highlight" }] } });
  assert.deepEqual(log.sent[0].toolResponse.functionResponses.map((x) => x.response.result), ["unknown function", "no such sentence id"]);
  assert.deepEqual(log.hl, []);
});

test("goAway is passed on; junk messages are ignored", () => {
  const { p, log } = proto();
  p.handle({ goAway: { timeLeft: "30s" } });
  p.handle(null); p.handle("text"); p.handle({}); p.handle({ serverContent: {} });
  assert.deepEqual(log.events, [["goAway", "30s"]]);
});

test("setup carries the chosen voice, and a language code only when one is given", () => {
  const a = setupMessage({ model: "m", instruction: "R", voice: "Achird" }).setup;
  assert.equal(a.speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName, "Achird");
  assert.ok(!("languageCode" in a.speechConfig));
  const b = setupMessage({ model: "m", instruction: "R", voice: "Achird", languageCode: "en-IN" }).setup;
  assert.equal(b.speechConfig.languageCode, "en-IN");
  const c = setupMessage({ model: "m", instruction: "R", languageCode: "hi-IN", nested: true }).setup;
  assert.equal(c.generationConfig.speechConfig.languageCode, "hi-IN");
});

// -- the noise gate: background noise must not keep the reader's turn open ----------------------------------------
const feed = (g, level, ms, step = 32) => { const out = []; for (let t = 0; t < ms; t += step) out.push(g.process(level, step)); return out; };

test("steady room noise (a fan, traffic) is shut out, once the gate knows the room", () => {
  const g = new NoiseGate();
  feed(g, 0.012, 1000);
  assert.ok(feed(g, 0.012, 3000).every((o) => !o));
  const g2 = new NoiseGate();                   // a noisier room, still below what the gate treats as speech
  feed(g2, 0.03, 1000);
  assert.ok(feed(g2, 0.03, 3000).every((o) => !o));
});

test("speech over the noise opens it at once, and it closes shortly after the reader stops", () => {
  const g = new NoiseGate();
  feed(g, 0.02, 1000);
  assert.equal(g.process(0.15, 32), true);      // the first chunk of speech is let through
  assert.ok(feed(g, 0.15, 6000).every(Boolean), "a long sentence is never cut: the floor cannot climb into the speech");
  feed(g, 0.02, 500);                           // past the hangover
  assert.equal(g.open, false);
  assert.ok(feed(g, 0.02, 2000).every((o) => !o), "noise after the reader stopped goes through as silence, so the turn can end");
});

test("a breath between words does not close the gate; a real pause does", () => {
  const g = new NoiseGate();
  feed(g, 0.01, 1000);
  feed(g, 0.12, 500);
  assert.ok(feed(g, 0.01, 250).every(Boolean));
  assert.equal(feed(g, 0.01, 600).pop(), false);
});

test("silence in a quiet room never opens the gate; the reader talking from the first moment still gets through", () => {
  assert.ok(feed(new NoiseGate(), 0.001, 2000).every((o) => !o));
  const g = new NoiseGate();                    // loud from the very first chunk: the floor is capped, so speech still passes
  assert.ok(feed(g, 0.12, 3000).every(Boolean));
});
