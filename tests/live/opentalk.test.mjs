// node --test tests/live
// Opening another article (owner, Oct 13 2026; article and recap guides): open_article is answered LATER, with the article's text, and never SILENT.
import test from "node:test";
import assert from "node:assert/strict";
import { LiveProtocol } from "../../live/talk.js";

const call = (args, id = "c1") => ({ toolCall: { functionCalls: [{ id, name: "open_article", args }] } });
const tick = () => new Promise((r) => setTimeout(r, 5));

test("the article's text goes back as the function's answer, once it has arrived", async () => {
  const sent = [], asked = [];
  const p = new LiveProtocol({ sentenceIds: [], send: (m) => sent.push(m), nonBlocking: true,
    on: { open: async (id) => { asked.push(id); await tick(); return { ok: true, text: "OPENED ARTICLE (story 7): Big story" }; } } });
  p.handle(call({ story_id: "7" }));
  assert.deepEqual(sent, []);                                  // nothing is answered before the text is there
  await tick(); await tick();
  assert.deepEqual(asked, ["7"]);
  assert.equal(sent.length, 1);
  const r = sent[0].toolResponse.functionResponses[0];
  assert.equal(r.id, "c1"); assert.equal(r.name, "open_article");
  assert.match(r.response.article, /OPENED ARTICLE \(story 7\)/);
  assert.equal(r.scheduling, undefined);                       // even when highlight is non-blocking, THIS answer must let the guide carry on
});

test("an article that could not be opened is told to the guide in words, so it never freezes", async () => {
  for (const open of [async () => ({ ok: false }), async () => { throw new Error("net"); }, undefined]) {
    const sent = [];
    const p = new LiveProtocol({ sentenceIds: [], send: (m) => sent.push(m), on: { open } });
    p.handle(call({ story_id: "9" }));
    await tick(); await tick();
    assert.equal(sent.length, 1);
    assert.match(sent[0].toolResponse.functionResponses[0].response.error, /could not be opened/);
  }
});

test("a highlight and an open_article in the same turn: the highlight is answered at once, the article when it arrives", async () => {
  const sent = [], lit = [];
  const p = new LiveProtocol({ sentenceIds: ["p0s0"], send: (m) => sent.push(m), on: { highlight: (id) => lit.push(id), open: async () => { await tick(); return { ok: true, text: "x" }; } } });
  p.handle({ toolCall: { functionCalls: [{ id: "a", name: "highlight", args: { sentence_id: "p0s0" } }, { id: "b", name: "open_article", args: { story_id: "1" } }] } });
  assert.equal(sent.length, 1);
  assert.equal(sent[0].toolResponse.functionResponses[0].id, "a");
  await tick(); await tick();
  assert.equal(sent.length, 2);
  assert.equal(sent[1].toolResponse.functionResponses[0].id, "b");
  assert.deepEqual(lit, ["p0s0"]);
});
