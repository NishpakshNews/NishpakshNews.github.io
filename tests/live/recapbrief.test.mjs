// node --test tests/live
// The Daily recap's talk guide (owner, Oct 12 2026): what it is given, and that it stays small.
import test from "node:test";
import assert from "node:assert/strict";
import { buildRecapBrief } from "../../supabase/functions/live-token/recapbrief.ts";
import { toolsFor } from "../../supabase/functions/live-token/brief.ts";
import { DEFAULT_STYLE } from "../../supabase/functions/live-token/voice.ts";

const row = () => ({
  day: "2026-10-12",
  payload_en: {
    day: "2026-10-12", kind: "brief",
    sections: [
      { key: "politics", label: "Politics", sents: [
        { t: "The Centre and the states agreed a new GST council date, officials said.", c: "established", id: 11 },
        { t: "The opposition walked out of the House.", c: "single", id: 12 } ] },
      { key: "business", label: "Business", sents: [{ t: "The RBI kept the repo rate at 5.5 per cent.", c: "developing", id: 21 }] },
    ],
    stories: [
      { id: 11, h: "GST council to meet", n: 5, lead: [{ t: "The Centre and the states agreed a new GST council date, officials said.", c: "established" }, { t: "It will meet on the 20th.", c: "unverified" }] },
      { id: 12, h: "Walkout in the House", n: 1, lead: [{ t: "The opposition walked out of the House on Monday.", c: "single" }] },
      { id: 21, h: "RBI holds rates", n: 7, lead: [{ t: "The RBI kept the repo rate at 5.5 per cent.", c: "developing" }] },
    ],
  },
  payload_hi: {
    day: "2026-10-12", kind: "brief",
    sections: [{ key: "politics", label: "राजनीति", sents: [{ t: "जीएसटी परिषद की तारीख़ तय हुई।", c: "established", id: 11 }] }],
    stories: [{ id: 11, h: "जीएसटी परिषद की बैठक", n: 5, lead: [{ t: "जीएसटी परिषद की तारीख़ तय हुई।", c: "established" }] }],
  },
});

test("every story is one numbered line the guide may highlight: s<story id>, in the recap's own order", () => {
  const b = buildRecapBrief(row(), "en");
  assert.deepEqual(b.sentenceIds, ["s11", "s12", "s21"]);
  assert.equal(b.lang, "en");
  assert.match(b.instruction, /SECTION: Politics\n\[s11\] GST council to meet \| 5 outlets/);
  assert.match(b.instruction, /SECTION: Business\n\[s21\] RBI holds rates \| 7 outlets/);
  assert.match(b.instruction, /SECTIONS TODAY: Politics, Business/);
});

test("each line carries the colour the recap shows, in words, and never a stronger one; one outlet is said as one", () => {
  const ins = buildRecapBrief(row(), "en").instruction;
  assert.match(ins, /\[s12\] Walkout in the House \| 1 outlet\n {2}SUMMARY \(SINGLE SOURCE\): The opposition walked out of the House\./);
  assert.match(ins, /\[s21\] RBI holds rates \| 7 outlets\n {2}SUMMARY \(DEVELOPING\)/);
  assert.match(ins, /MORE \(NOT CONFIRMED\): It will meet on the 20th\./);
});

test("the summary is not said twice when it is the lead's own first sentence", () => {
  const ins = buildRecapBrief(row(), "en").instruction;
  assert.equal(ins.split("The RBI kept the repo rate at 5.5 per cent.").length - 1, 1, "only in the summary");
  assert.doesNotMatch(ins, /\[s21\][^\[]*MORE \(/);
});

test("Hindi when asked and there is a Hindi recap; the English recap otherwise", () => {
  const hi = buildRecapBrief(row(), "hi");
  assert.equal(hi.lang, "hi");
  assert.deepEqual(hi.sentenceIds, ["s11"]);
  assert.match(hi.instruction, /SECTION: राजनीति/);
  const r = row(); r.payload_hi = null;
  assert.equal(buildRecapBrief(r, "hi").lang, "en");
});

test("an older recap (stories with a lead, no sections) still works, and one with nothing is refused", () => {
  const old = { day: "2026-10-09", payload_en: { stories: [{ id: 5, h: "Old story", lead: [{ t: "It happened.", c: "established" }, { t: "More.", c: "single" }] }] } };
  const b = buildRecapBrief(old, "en");
  assert.deepEqual(b.sentenceIds, ["s5"]);
  assert.match(b.instruction, /\[s5\] Old story\n {2}SUMMARY \(ESTABLISHED\): It happened\.\n {2}MORE \(SINGLE SOURCE\): More\./);
  assert.equal(buildRecapBrief({ day: "x", payload_en: { sections: [], stories: [] } }, "en"), null);
  assert.equal(buildRecapBrief({ day: "x" }, "en"), null);
});

test("a recap from the days before leads were stored (summary only) works too", () => {
  const r = row(); r.payload_en.stories = r.payload_en.stories.map((s) => ({ id: s.id, h: s.h }));
  const ins = buildRecapBrief(r, "en").instruction;
  assert.match(ins, /\[s11\] GST council to meet\n {2}SUMMARY \(ESTABLISHED\)/);
  assert.doesNotMatch(ins, /^ {2}MORE \(/m);
});

test("a suicide story adds the Tele-MANAS rules; no other recap does", () => {
  assert.doesNotMatch(buildRecapBrief(row(), "en").instruction, /Tele-MANAS/);
  const r = row(); r.payload_en.stories[1].sx = 1;
  assert.match(buildRecapBrief(r, "en").instruction, /Tele-MANAS/);
});

test("the guide is told the traps: not more certain than the status, no outside facts, no 'shall I go on', tap to open", () => {
  const ins = buildRecapBrief(row(), "en").instruction;
  assert.match(ins, /SINGLE SOURCE is not confirmed/);
  assert.match(ins, /Never say a name, number, place or date that is not in the lines/);
  assert.match(ins, /Do not ask "Shall I go on\?"/);
  assert.match(ins, /call open_article with that story's number/);          // depth: the guide opens the story's article itself
  assert.match(ins, /tap its line in the recap, then use Listen/);          // a whole article read out: the recap's Listen
  assert.match(ins, /STATUSES \(what each label means\)/);
});

test("it stays small: sixty stories with their opening sentences are a few thousand words, not sixty articles", () => {
  const r = row(); const sents = [], stories = [];
  for (let i = 0; i < 60; i++) {
    const t = `Story number ${i} happened today in a part of the country, officials said on Monday evening after a long meeting.`;
    sents.push({ t, c: "established", id: 100 + i });
    stories.push({ id: 100 + i, h: `Headline of story ${i}`, n: 3, lead: [{ t, c: "established" }, { t: `A second sentence about story ${i} that adds a little more detail for the reader.`, c: "single" }] });
  }
  r.payload_en.sections = [{ key: "politics", label: "Politics", sents }]; r.payload_en.stories = stories;
  const b = buildRecapBrief(r, "en");
  assert.equal(b.sentenceIds.length, 60);
  const words = b.instruction.split(/\s+/).length;
  assert.ok(words < 6000, `the instruction is ${words} words`);          // one article guide with 3 earlier articles is ~2000-3000; sixty full articles would be ~40000
});

test("a story that appears twice, a line without an id or text, and a runaway recap are handled", () => {
  const r = row();
  r.payload_en.sections[0].sents.push({ t: "Again.", c: "established", id: 11 }, { t: "", c: "established", id: 99 }, { t: "No id.", c: "established" });
  assert.deepEqual(buildRecapBrief(r, "en").sentenceIds, ["s11", "s12", "s21"]);
  const big = row(); const sents = [];
  for (let i = 0; i < 200; i++) sents.push({ t: `S${i}.`, c: "established", id: 1000 + i });
  big.payload_en.sections = [{ key: "more", label: "Also today", sents }];
  assert.equal(buildRecapBrief(big, "en").sentenceIds.length, 80);
});

test("the style block is in, so the guide sounds like the reader chose", () => {
  assert.match(buildRecapBrief(row(), "en", { ...DEFAULT_STYLE, tone: "news" }).instruction, /newsreader/);
});

test("highlight is described for the recap, with the same function and parameter the browser already handles", () => {
  const t = toolsFor(false, "recap")[0].functionDeclarations[0];
  assert.equal(t.name, "highlight");
  assert.match(t.description, /recap/);
  assert.match(t.description, /s1234/);
  assert.deepEqual(t.parameters.required, ["sentence_id"]);
  assert.match(toolsFor(false)[0].functionDeclarations[0].description, /p2s0/, "the article's stays as it was");
  assert.equal(toolsFor(true, "recap")[0].functionDeclarations[0].behavior, "NON_BLOCKING");
});
