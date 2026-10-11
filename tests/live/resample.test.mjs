// The guide's 24 kHz chunks are resampled to the AudioContext's rate with no seam between chunks (live/talk.js Resampler).
import test from "node:test";
import assert from "node:assert/strict";
import { Resampler } from "../../live/talk.js";

const sine = (n, hz, rate, from = 0) => Float32Array.from({ length: n }, (_, i) => 0.5 * Math.sin((2 * Math.PI * hz * (from + i)) / rate));

test("chunk by chunk gives the same samples as the whole stream at once (no seam at the joints)", () => {
  const whole = sine(4800, 440, 24000);
  const one = new Resampler(24000, 48000).process(whole);
  const rs = new Resampler(24000, 48000);
  const parts = [];
  for (let i = 0; i < whole.length; ) { const n = [37, 480, 1, 1000, 250][parts.length % 5]; parts.push(rs.process(whole.slice(i, i + n))); i += n; }
  const joined = Float32Array.from(parts.flatMap((p) => [...p]));
  assert.ok(Math.abs(joined.length - one.length) <= 2);
  for (let i = 0; i < Math.min(joined.length, one.length) - 2; i++) assert.ok(Math.abs(joined[i] - one[i]) < 1e-6, `sample ${i}`);
});

test("no jump anywhere: neighbouring samples of a sine never differ by more than the sine itself allows", () => {
  const rs = new Resampler(24000, 44100);
  const out = [];
  let from = 0;
  for (let c = 0; c < 40; c++) { const n = 480 + (c % 3) * 7; out.push(...rs.process(sine(n, 300, 24000, from))); from += n; }
  let worst = 0;
  for (let i = 1; i < out.length; i++) worst = Math.max(worst, Math.abs(out[i] - out[i - 1]));
  assert.ok(worst < 0.1, `largest step ${worst}`);          // 300 Hz at amplitude 0.5: about 0.02 a sample
});

test("the length follows the rates, and equal rates pass through untouched", () => {
  const out = new Resampler(24000, 48000).process(new Float32Array(2400).fill(0.1));
  assert.ok(Math.abs(out.length - 4800) <= 2);
  const f = new Float32Array([0.1, 0.2]);
  assert.equal(new Resampler(24000, 24000).process(f), f);
  assert.equal(new Resampler(24000, 48000).process(new Float32Array(0)).length, 0);
});
