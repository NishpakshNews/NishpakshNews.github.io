// Test harness: the real site/index.html in Chromium, the feed and Supabase stubbed, live/talk.js replaced by a mock
// the test drives by hand (no microphone, no Gemini here).
const { chromium } = require("playwright");
const http = require("http"), fs = require("fs"), path = require("path");
const SHOTS = process.env.SHOTS || "/tmp";   // where screenshots go
const SITE = path.join(__dirname, "..", "..", "site");

const cls = ["established", "established", "single", "disputed", "partial", "unverified", "developing"];
function sentences(n, seed, hi) {
  const en = ["The minister said the new rule takes effect from the first of next month.", "Three outlets report that the committee met on Tuesday.", "Only one outlet says the decision was taken without a vote.", "Opposition leaders disputed the figures presented in the house.", "Officials said the work would cost about 40 crore rupees.", "It is not yet clear who will pay for the repairs.", "A court is due to hear the matter next week."];
  const hindi = ["मंत्री ने कहा कि नया नियम अगले महीने की पहली तारीख़ से लागू होगा।", "तीन समाचार माध्यमों के अनुसार समिति की बैठक मंगलवार को हुई।", "केवल एक माध्यम का कहना है कि फ़ैसला बिना मतदान के हुआ।", "विपक्षी नेताओं ने सदन में रखे आँकड़ों पर आपत्ति जताई।", "अधिकारियों ने कहा कि काम पर क़रीब 40 करोड़ रुपये ख़र्च होंगे।", "अभी साफ़ नहीं है कि मरम्मत का ख़र्च कौन उठाएगा।", "अदालत अगले हफ़्ते इस मामले की सुनवाई करेगी।"];
  const src = hi ? hindi : en;
  return Array.from({ length: n }, (_, i) => ({ text: src[(i + seed) % src.length], class: cls[(i + seed) % cls.length], sources: [1 + ((i + seed) % 3)] }));
}
function story(hi) {
  const paras = [sentences(3, 0, hi), sentences(3, 2, hi), sentences(4, 1, hi), sentences(3, 4, hi), sentences(2, 3, hi), sentences(4, 5, hi), sentences(4, 6, hi), sentences(3, 1, hi), sentences(4, 2, hi)];
  return { narrative: { paragraphs: paras, section_keys: ["news", "happened", "happened", "say", "background", "background", "explained", "next", "next"], who: [], sources: [1, 2, 3].map((n) => ({ n, outlet: ["The Hindu", "PTI", "Indian Express"][n - 1], title: "Report " + n, url: "https://example.com/" + n, read: true })) }, counts: { independent_sources: 3, outlets: 5 } };
}
const STORY = { story_id: 1, updated_at: "2026-10-11T05:00:00", headline_en: "Committee approves the new bridge rules after a long debate", headline_hi: "लंबी बहस के बाद समिति ने पुल के नए नियमों को मंज़ूरी दी", payload_en: story(false), payload_hi: story(true) };
const CARD = (l) => ({ id: 1, at: "2026-10-11T05:00:00", thread: 1, h: l === "hi" ? STORY.headline_hi : STORY.headline_en, paras: [[{ t: "The minister said the new rule takes effect next month.", c: "established" }, { t: "Opposition leaders disputed the figures.", c: "disputed" }]], bar: { e: 5, v: 1, p: 2, o: 2, d: 2, r: 0, u: 1 }, n: 3, cat: { primary: ["politics"], secondary: ["government"], tertiary: [] }, w: 300, pl: [], pp: [] });

const MOCK = `
export function createTalk(o) {
  let state = "idle";
  const set = (s) => { state = s; o.onState(s); };
  window.__log = [];
  window.__mock = {
    set, level: (v) => o.onLevel(v), highlight: (id) => o.onHighlight(id), transcript: (l) => o.onTranscript(l),
    end: (reason) => { set("ended"); o.onEnd({ reason }); },
    opts: o,
  };
  return {
    start: async (a) => { window.__log.push(["start", a]); set("connecting"); },
    stop: () => { window.__log.push(["stop"]); set("ended"); o.onEnd({ reason: "stopped" }); },
    nudge: (t) => { window.__log.push(["nudge", t]); },
    skipIntro() {}, setMuted: (m) => { window.__log.push(["mute", !!m]); },
    get state() { return state; },
  };
}`;

function serve() {
  return new Promise((res) => {
    const srv = http.createServer((q, r) => {
      let f = path.join(SITE, decodeURIComponent(q.url.split("?")[0]));
      if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, "index.html");
      if (!fs.existsSync(f)) { r.writeHead(404); r.end(); return; }
      const t = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".png": "image/png", ".webmanifest": "application/json" }[path.extname(f)] || "application/octet-stream";
      r.writeHead(200, { "Content-Type": t }); r.end(fs.readFileSync(f));
    }).listen(0, () => res(srv));
  });
}

async function open({ lang = "en", width = 390, height = 844, signedIn = true, withModule = true, reducedMotion = "no-preference" } = {}) {
  const srv = await serve(), port = srv.address().port;
  const browser = await chromium.launch(process.env.CHROME ? { executablePath: process.env.CHROME } : {});
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, reducedMotion, serviceWorkers: "block" });
  await ctx.addInitScript(([signedIn, lang]) => {
    try {
      localStorage.setItem("np-lang", lang);
      if (signedIn) localStorage.setItem("np-me", JSON.stringify({ name: "Asha", email: "a@b.c", access_token: "x.eyJzdWIiOiJ1MSJ9.z", refresh_token: "r", expires_at: Math.floor(Date.now() / 1000) + 99999 }));
    } catch (e) {}
  }, [signedIn, lang]);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.log("PAGE ERROR:", e.message));
  page.on("console", (m) => { if (m.type() === "error" || /Understand by talking is off/.test(m.text())) console.log("console:", m.text().slice(0, 200)); });
  await page.route("**/*", async (route) => {
    const u = route.request().url();
    if (u.startsWith(`http://localhost:${port}`) || u.startsWith(`http://127.0.0.1:${port}`)) {
      if (/\/live\/talk\.js/.test(u)) return withModule ? route.fulfill({ status: 200, contentType: "text/javascript", body: MOCK }) : route.fulfill({ status: 404, body: "" });
      if (/\/live\/intro\.json/.test(u)) return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
      return route.continue();
    }
    if (/raw\.githubusercontent\.com.*\/feed\/(en|hi)\.json/.test(u)) { const l = /hi\.json/.test(u) ? "hi" : "en"; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ stories: [CARD(l)], sections: null, places: [] }) }); }
    if (/raw\.githubusercontent\.com.*\/feed\/story\/1\.json/.test(u)) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(STORY) });
    if (/supabase\.co\/rest\/v1\//.test(u)) return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    return route.abort();
  });
  await page.goto(`http://localhost:${port}/index.html#/story/1`);
  await page.waitForSelector("#sheet.open .acts .talkbtn", { state: "attached", timeout: 8000 });
  await page.waitForTimeout(900);
  return { page, browser, srv, close: async () => { await browser.close(); srv.close(); } };
}
const shot = (page, name) => page.screenshot({ path: `${SHOTS}/${name}.png` });
module.exports = { open, shot, SHOTS };
