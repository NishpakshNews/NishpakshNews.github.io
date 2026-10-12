import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(fileURLToPath(import.meta.url));
const html = readFileSync(path.resolve(here, "../../site/index.html"), "utf8");
const start = html.indexOf("// Gemini Live transcription offsets are Durations");
const end = html.indexOf("function tkSyncCaptionUnits", start);
if (start < 0 || end < 0) throw new Error("Could not locate Talkbot caption helpers in site/index.html");
const sandbox = {
  document: {
    createElement: () => ({
      getContext: () => ({ font: "", measureText: (text) => ({ width: String(text).length * 6 }) }),
    }),
  },
};
vm.runInNewContext(html.slice(start, end), sandbox);
const build = (...args) => sandbox.tkBuildCaptionUnits(...args);

test("captions are prepared as complete four-word display units, not individual words", () => {
  const result = build("The voice moves line by line now", [], true, 3.2, 1000, "14px sans-serif");
  assert.equal(result.units.length, 2);
  assert.equal(result.units[0].text, "The voice moves line");
  assert.equal(result.units[1].text, "by line now");
});

test("an unfinished short tail stays buffered until the response is complete", () => {
  const streaming = build("The voice moves line by line", [], false, 0, 1000, "14px sans-serif");
  assert.equal(streaming.units.length, 1);
  assert.equal(streaming.units[0].text, "The voice moves line");
  const complete = build("The voice moves line by line", [], true, 2.4, 1000, "14px sans-serif");
  assert.equal(complete.units.length, 2);
  assert.equal(complete.units[1].text, "by line");
});

test("transcript audio offsets are mapped onto complete line units", () => {
  const text = "The guide speaks each line";
  const result = build(text, [{ text, startIndex: 0, endIndex: text.length, startOffset: "0s", endOffset: "2.5s" }], true, 2.5, 1000, "14px sans-serif");
  assert.equal(result.allTimed, true);
  assert.equal(result.units[0].text, "The guide speaks each");
  assert.equal(result.units[0].start, 0);
  assert.ok(result.units[0].end < result.units[1].start);
});

test("line units break at a natural sentence boundary after three words", () => {
  const result = build("This sentence ends. Then it continues", [], true, 3.5, 1000, "14px sans-serif");
  assert.equal(result.units[0].text, "This sentence ends.");
  assert.equal(result.units[1].text, "Then it continues");
});


test("the four-word target can extend to five words to avoid a dangling function word", () => {
  const result = build("We are going to meet later today", [], true, 3.1, 1000, "14px sans-serif");
  assert.equal(result.units[0].text, "We are going to meet");
  assert.equal(result.units[1].text, "later today");
});

test("a timed segment does not make an unfinished trailing token commit early", () => {
  const text = "The guide explains why subj";
  const result = build(text, [{ text, startIndex: 0, endIndex: text.length, startOffset: "0s", endOffset: "1.2s" }], false, 1.2, 1000, "14px sans-serif");
  assert.equal(result.units.length, 1);
  assert.equal(result.units[0].text, "The guide explains why");
});
