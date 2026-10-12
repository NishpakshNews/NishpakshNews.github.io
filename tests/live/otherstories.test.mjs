// node --test tests/live
// The other stories of today, listed for the article guide, and the open_article function in the article and recap guides (owner, Oct 13 2026).
import test from "node:test";
import assert from "node:assert/strict";
import { otherStories, todaysCards, agoWords, utcMs, MAX_OTHER } from "../../supabase/functions/live-token/otherstories.ts";
import { buildBrief, toolsFor, articleDigest } from "../../supabase/functions/live-token/brief.ts";
import { buildRecapBrief } from "../../supabase/functions/live-token/recapbrief.ts";

const NOW = Date.parse("2026-10-13T08:00:00Z");              // 13:30 IST
const card = (id, at, h, n = 3) => ({ id, at, h, n, paras: [[{ t: `Sentence of ${h}.`, c: "established" }]] });
const feed = { stories: [
  card(1, "2026-10-13T07:20:00", "Newest story", 4), card(2, "2026-10-13T05:00:00", "Morning story", 1), card(3, "2026-10-13T04:00:00", "Third story"),
  card(4, "2026-10-13T03:00:00", "Fourth story"), card(5, "2026-10-13T02:00:00", "Fifth story"), card(6, "2026-10-12T05:00:00", "Yesterday story"),
  { id: 7, at: "2026-10-13T06:00:00", h: "No sentence", paras: [] }, { id: 8, h: "No time", paras: [[{ t: "x" }]] },
] };

test("the list is today's stories, newest first, without the story the reader is on, yesterday's, or broken cards", () => {
  const l = otherStories(feed, "en", 1, NOW);
  assert.deepEqual(l.map((x) => x.slice(0, 4)), ["[a2]", "[a3]", "[a4]", "[a5]"]);
  assert.match(l[0], /^\[a2\] 3 hours ago \| 1 outlet \| Morning story$/);
  assert.match(otherStories(feed, "en", 99, NOW)[0], /^\[a1\] 40 minutes ago \| 4 outlets \| Newest story$/);
  assert.ok(!otherStories(feed, "en", 99, NOW).some((x) => /Yesterday|No sentence|No time/.test(x)));
});

test("Hindi times and outlets; an early-morning day with few stories uses the last 24 hours; a missing feed gives no list", () => {
  assert.match(otherStories(feed, "hi", 99, NOW)[0], /40 मिनट पहले \| 4 स्रोत/);
  assert.equal(agoWords(NOW, NOW, "en"), "just now");
  const early = Date.parse("2026-10-13T00:30:00Z");           // 06:00 IST: fewer than 5 today
  assert.ok(todaysCards({ stories: [card(1, "2026-10-12T20:00:00", "Last night"), card(2, "2026-10-12T22:00:00", "Late")] }, early).length === 2);
  assert.deepEqual(otherStories(null, "en", 1, NOW), []);
  assert.deepEqual(otherStories({}, "en", 1, NOW), []);
  assert.ok(Number.isNaN(utcMs("")));
});

test("the list is capped", () => {
  const many = { stories: Array.from({ length: 100 }, (_, i) => card(i + 1, `2026-10-13T0${Math.floor(i / 20)}:${String(i % 20 + 10).padStart(2, "0")}:00`, `Story ${i}`)) };
  assert.equal(otherStories(many, "en", 0, NOW).length, MAX_OTHER);
});

const story = { story_id: 5, payload_en: { narrative: { paragraphs: [[{ text: "The bridge opened.", class: "established", sources: [1] }]], section_keys: ["news"], sources: [{ n: 1, outlet: "PTI", read: true }] } } };

test("an article's guide gets the list and knows to open other stories; without the list it is told it cannot", () => {
  const withList = buildBrief(story, "en", undefined, [], ["[a2] 3 hours ago | 1 outlet | Morning story"]);
  assert.match(withList.instruction, /OPENING ANOTHER ARTICLE/);
  assert.match(withList.instruction, /OTHER STORIES TODAY \(newest first[^\n]*\n\[a2\] 3 hours ago/);
  const without = buildBrief(story, "en");
  assert.match(without.instruction, /OTHER STORIES TODAY: \(the list is not available/);
});

test("both guides declare open_article next to highlight; nothing else changed in highlight", () => {
  for (const kind of ["article", "recap"]) {
    const d = toolsFor(false, kind)[0].functionDeclarations;
    assert.deepEqual(d.map((x) => x.name), ["highlight", "open_article"]);
    assert.equal(d[1].behavior, undefined);                  // blocking, even when highlight is non-blocking
    assert.equal(toolsFor(true, kind)[0].functionDeclarations[1].behavior, undefined);
    assert.equal(toolsFor(true, kind)[0].functionDeclarations[0].behavior, "NON_BLOCKING");
  }
});

test("the recap guide is told to open an article for depth, using the story's number", () => {
  const row = { day: "2026-10-13", payload_en: { sections: [{ key: "p", label: "Politics", sents: [{ t: "A thing happened.", c: "established", id: 11 }] }], stories: [{ id: 11, h: "A thing", n: 2, lead: [] }] } };
  const b = buildRecapBrief(row, "en");
  assert.match(b.instruction, /OPENING AN ARTICLE/);
  assert.match(b.instruction, /digits after the s/);
  assert.ok(!/does not give you the full articles|You have nothing else/.test(b.instruction));
});

test("an opened article is labelled and can be longer than an earlier one", () => {
  const d = articleDigest(story, "en", 80, "OPENED ARTICLE");
  assert.match(d.text, /^OPENED ARTICLE \(story 5\): /);
  assert.match(articleDigest(story, "en").text, /^EARLIER ARTICLE \(story 5\)/);
});
