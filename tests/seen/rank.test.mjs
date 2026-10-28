import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";

const here = path.dirname(fileURLToPath(import.meta.url));
const html = readFileSync(path.resolve(here, "../../site/index.html"), "utf8");
const a = html.indexOf("// UNSEEN-START"), b = html.indexOf("// UNSEEN-END");
if (a < 0 || b < 0) throw new Error("Could not locate the unseen-first block in site/index.html");
let store = "{}";
const sb = { safeGet: () => store, JSON, Date, Object, String, Math };
vm.runInNewContext(html.slice(a, b) + "\nthis.api = {rankCards, readSeen, seenKey};", sb);
const { rankCards, readSeen } = sb.api;
const verOf = c => c.at;
const card = (id, o = {}) => ({ id, at: "t" + id, thread: "th" + id, bar: { e: 2, d: 0 }, ...o });
const rec = (c, o = {}) => ({ v: c.at, i: c.id, b: [2, 0, 0, 0, 0, 0, 0], s: 1, o: 0, ...o });
const ids = r => Array.from(r.ordered, c => c.id);
const plain = x => JSON.parse(JSON.stringify(x));   // objects made inside the vm sandbox have another realm's prototypes

test("no records: all unseen, order untouched, no pills", () => {
  const cs = [card(1), card(2), card(3)];
  const r = rankCards(cs, {}, verOf);
  assert.deepEqual(ids(r), [1, 2, 3]);
  assert.equal(r.counts.fresh, 3);
  assert.ok(cs.every(c => c.upd === null));
});
test("unseen, then seen, then opened; newest first inside each", () => {
  const cs = [card(1), card(2), card(3), card(4), card(5)];
  const recs = { th1: rec(cs[0], { o: 9 }), th2: rec(cs[1]), th4: rec(cs[3], { o: 9 }), th5: rec(cs[4]) };
  assert.deepEqual(ids(rankCards(cs, recs, verOf)), [3, 2, 5, 1, 4]);
});
test("a changed version goes back to the top with a pill", () => {
  const cs = [card(1), card(2, { at: "t2new", bar: { e: 3, d: 0 } })];
  const recs = { th1: rec(cs[0]), th2: rec(cs[1], { v: "t2" }) };
  const r = rankCards(cs, recs, verOf);
  assert.deepEqual(ids(r), [2, 1]);
  assert.deepEqual(plain(cs[1].upd), { r: "updated", n: 0 });
  assert.equal(r.counts.upd, 1);
});
test("a different story id on the same thread (a follow-up) is updated too", () => {
  const c = card(7, { thread: "th1", at: "n" });
  rankCards([c], { th1: rec(c, { i: 1, v: "old" }) }, verOf);
  assert.equal(c.upd.r, "updated");
});
test("annotation is reset on every call", () => {
  const c = card(1, { at: "n" });
  rankCards([c], { th1: rec(c, { v: "old" }) }, verOf);
  assert.ok(c.upd);
  rankCards([c], {}, verOf);
  assert.equal(c.upd, null);
});
test("records older than 4 days are dropped, newer kept", () => {
  const now = Date.now();
  store = JSON.stringify({ old: { s: now - 5 * 86400000, o: 0 }, fresh: { s: now - 1000, o: 0 }, op: { s: 1, o: now - 3600000 } });
  assert.deepEqual(Array.from(Object.keys(readSeen(now))).sort(), ["fresh", "op"]);
});
test("at most 500 records, most recent kept", () => {
  const now = Date.now(), o = {};
  for (let i = 0; i < 600; i++) o["k" + i] = { s: now - i, o: 0 };
  store = JSON.stringify(o);
  const r = readSeen(now);
  assert.equal(Object.keys(r).length, 500);
  assert.ok(r.k0 && !r.k599);
});
test("broken storage reads as empty", () => {
  store = "{not json";
  assert.deepEqual(Array.from(Object.keys(readSeen())), []);
});
