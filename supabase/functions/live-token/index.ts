// "Talk to the article": the door to a live voice conversation (owner, Oct 11 2026).
//
// The browser talks to Gemini's Live API directly (one WebSocket, no proxy), but never holds a Gemini key. It asks
// here first. This function: (1) checks the reader is logged in, (2) asks the database whether they may start one
// (live_talk_begin: a few a day each, and a cap on how many run at the same moment across the site), (3) reads the
// article from the feed branch, plus the earlier articles of the same story (its parents), and builds what the model may use (brief.ts), (4) asks Gemini for a ONE-USE token that
// is locked to the Live model and to that instruction, and expires when the longest allowed conversation does, and
// (5) hands the browser the token, the instruction (so it can repeat it in its setup message), and the ids of the
// sentences the model may light up.
//
// Deployed with verify_jwt off, like `account`: the site calls it with the publishable key, and the reader's own
// access token is checked here. Secrets: GEMINI_API_KEY, GEMINI_API_KEY_2, ... (the same keys the pipeline uses;
// each from its own project, so conversations are spread over them). Optional: LIVE_MODEL, FEED_URL, LIVE_LANGUAGE_CODE=1
// (also send a language code to Gemini; off by default), LIVE_NONBLOCKING=1, LIVE_THINKING_CONFIG (JSON, e.g. {"thinkingBudget":0}). The request may carry `style` {voice, pace, tone, accent}.
import { createClient } from "npm:@supabase/supabase-js@2.45.4";
import { buildBrief, toolsFor, type Story } from "./brief.ts";
import { cleanStyle, languageCode, thinkingConfig } from "./voice.ts";

const URL_ = Deno.env.get("SUPABASE_URL")!;
const SERVICE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const admin = createClient(URL_, SERVICE, { auth: { persistSession: false, autoRefreshToken: false } });

const MODEL = Deno.env.get("LIVE_MODEL") || "gemini-3.8-live";
const SEND_LANGUAGE_CODE = Deno.env.get("LIVE_LANGUAGE_CODE") === "1";   // see voice.ts: off until the model is known to accept it
const NON_BLOCKING = Deno.env.get("LIVE_NONBLOCKING") === "1";           // see brief.ts toolsFor: highlight need not stop the guide; off until the model is known to accept it
const THINKING = thinkingConfig(Deno.env.get("LIVE_THINKING_CONFIG"));       // see voice.ts thinkingConfig: how long the model may reason before it speaks; nothing is sent unless the secret is set (a big question made the guide go silent)
const NOISE_GATE = Deno.env.get("LIVE_NOISE_GATE") !== "0";           // "0" turns the browser's noise gate off (live/talk.js NoiseGate): the microphone audio then goes to Gemini as it is, for a reader the gate keeps shutting out
const FEED_URL = Deno.env.get("FEED_URL") || "https://raw.githubusercontent.com/NishpakshNews/NishpakshNews.github.io/feed";
const KEYS = [...new Set(["GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY_4", "GEMINI_API_KEY_5"]
  .map((k) => (Deno.env.get(k) || "").trim()).filter(Boolean))];

const HOURLY = Number(Deno.env.get("LIVE_HOURLY")) || 3;   // conversations per reader in each clock hour (XX:00 to XX:00, IST) (secret LIVE_HOURLY changes it)
const DAILY = 20;              // a high backstop per reader per IST day: a bug or a script cannot burn the site's Gemini quota
const CONCURRENT = Number(Deno.env.get("LIVE_CONCURRENT")) || 3;   // at the same moment, whole site; a guess to be tuned (Gemini 3.8 Live: 65K tokens a minute per project). Set the secret LIVE_CONCURRENT to change it
// How long the reader must be quiet before the guide starts answering: every answer waits this long first. Google's guidance is
// 500-800 ms (shorter splits a sentence at a breath); it was 700. The same number is in live/talk.js (the token is locked to this setup).
const SILENCE_MS = 500;
const MAX_SECONDS = 480;       // the longest conversation: the token itself expires then
const GEMINI = "https://generativelanguage.googleapis.com/v1beta/auth_tokens";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Max-Age": "7200",     // the browser remembers the permission check for two hours: no extra round trip before every call (the first call took 2 s of it, Oct 11 2026)
};
const reply = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json" } });

async function me(req: Request) {
  const tok = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!tok) return null;
  const { data } = await admin.auth.getUser(tok);
  return data?.user || null;
}

async function mint(key: string, instruction: string, voice: string): Promise<string> {
  const now = Date.now();
  const r = await fetch(GEMINI, {
    method: "POST",
    headers: { "x-goog-api-key": key, "Content-Type": "application/json" },
    body: JSON.stringify({
      uses: 1,
      // the conversation must start within a minute of this call, and ends at the latest MAX_SECONDS later
      newSessionExpireTime: new Date(now + 60_000).toISOString(),
      expireTime: new Date(now + (60 + MAX_SECONDS) * 1000).toISOString(),
      // REST name of what the SDKs call liveConnectConstraints: the setup the token is locked to
      // the token is locked to this whole setup (an empty field mask: the browser's own setup adds nothing), so everything the
      // conversation needs is here: the voice, the functions, the transcripts and the turn-taking
      bidiGenerateContentSetup: {
        model: `models/${MODEL}`,
        generationConfig: {
          responseModalities: ["AUDIO"],
          speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: voice } } },
          ...(THINKING ? { thinkingConfig: THINKING } : {}),
        },
        systemInstruction: { parts: [{ text: instruction }] },
        tools: toolsFor(NON_BLOCKING),
        inputAudioTranscription: {},
        outputAudioTranscription: {},
        realtimeInputConfig: { automaticActivityDetection: { silenceDurationMs: SILENCE_MS, prefixPaddingMs: 100 } },
      },
    }),
  });
  if (!r.ok) throw new Error(`gemini ${r.status}: ${(await r.text()).slice(0, 700)}`);
  const j = await r.json();
  if (!j?.name) throw new Error("gemini sent no token");
  return String(j.name);
}

// Articles read a moment ago are kept for a minute, so a second reader of the same story (or the same reader again) does not wait for GitHub.
// Only what this instance has already fetched; a story that changed is at most a minute old here.
const KEEP_MS = 60_000;
const kept = new Map<string, { at: number; story: Story }>();
async function getStory(id: number, timeoutMs = 0): Promise<{ ok: boolean; story: Story | null }> {
  const hit = kept.get(String(id));
  if (hit && Date.now() - hit.at < KEEP_MS) return { ok: true, story: hit.story };
  const r = await fetch(`${FEED_URL}/story/${id}.json`, timeoutMs ? { signal: AbortSignal.timeout(timeoutMs) } : undefined);
  if (!r.ok) return { ok: false, story: null };
  const story = (await r.json()) as Story;
  if (kept.size >= 60) kept.delete(kept.keys().next().value as string);
  kept.set(String(id), { at: Date.now(), story });
  return { ok: true, story };
}

// The earlier articles of THIS story: the entries of the page's own `parents` list (what the site shows under "Earlier in this
// story"), at most three, fetched together with a short timeout. Nothing else is fetched: not the feed, not other stories.
// A parent that cannot be read is simply left out; it never holds the conversation up for more than the timeout.
async function earlier(page: Story & { payload_en?: { parents?: unknown } | null }): Promise<Story[]> {
  const raw = page?.payload_en?.parents;
  const ids = (Array.isArray(raw) ? raw : [])
    .map((x: { story_id?: unknown }) => x?.story_id)
    .filter((n): n is number => Number.isInteger(n) && (n as number) > 0)
    .slice(0, 3);
  const got = await Promise.all(ids.map(async (id) => {
    try { return (await getStory(id, 2500)).story; } catch { return null; }
  }));
  return got.filter((x): x is Story => !!x);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return reply({ error: "POST only" }, 405);
  let b: Record<string, unknown> = {};
  try { b = await req.json(); } catch { return reply({ error: "bad request" }, 400); }
  const lang = b.lang === "hi" ? "hi" : "en";

  // the page says "a reader may tap soon" (an article was opened): nothing to do but be started, so the real call does not pay for the start
  if (b.warm !== undefined) return reply({ ok: true });

  // the browser says it is still there (every 15 s): a conversation that goes quiet for 45 s frees its place
  if (b.ping !== undefined) {
    const id = Number(b.ping);
    try {
      const user = await me(req);
      if (user && Number.isInteger(id) && id > 0) await admin.rpc("live_talk_ping", { p_id: id, p_reader: user.id });
    } catch { /* the next ping will do */ }
    return reply({ ok: true });
  }

  // the browser says a conversation is over: its place is free at once
  if (b.end !== undefined) {
    const id = Number(b.end);
    try {
      const user = await me(req);
      if (user && Number.isInteger(id) && id > 0) await admin.rpc("live_talk_end", { p_id: id, p_reader: user.id });
    } catch { /* nothing to do: the row expires by its age anyway */ }
    return reply({ ok: true });
  }

  const story = Number(b.story_id);
  if (!Number.isInteger(story) || story < 1) return reply({ error: "bad request" }, 400);
  if (!KEYS.length) return reply({ error: "not configured" }, 500);

  try {
    // where the time goes, in ms since the call began: returned to the page, which prints it in the browser console (talk timing)
    const t0 = Date.now(); const tm: Record<string, number> = {};
    const mark = <T>(k: string, p: Promise<T>) => p.then((v) => { tm[k] = Date.now() - t0; return v; });

    // the login check and the article are asked at the same time (they used to wait for each other)
    const [user, page] = await Promise.all([mark("login", me(req)), mark("article", getStory(story))]);
    if (!user) return reply({ error: "login" }, 401);

    // the article first: nothing is counted against the reader when there is nothing to talk about
    if (!page.ok || !page.story) return reply({ error: "gone" }, 404);
    const style = cleanStyle(b.style);                  // the reader's voice, pace, tone and accent: checked against fixed lists
    const main = page.story;
    const brief = buildBrief(main, lang, style, await mark("earlier", earlier(main)));
    if (!brief) return reply({ error: "gone" }, 404);

    const { data, error } = await admin.rpc("live_talk_begin", {
      p_reader: user.id, p_story: story, p_lang: brief.lang, p_hourly: HOURLY, p_daily: DAILY, p_concurrent: CONCURRENT, p_seconds: MAX_SECONDS,
    });
    tm.begin = Date.now() - t0;
    if (error) return reply({ error: error.message }, 500);
    const st = String(data?.status || "");
    if (st === "limit") return reply({ error: "limit", hourly: HOURLY, scope: data.scope, resets_at: data.resets_at, retry_minutes: data.retry_minutes }, 429);
    if (st === "busy") return reply({ error: "busy" }, 503);
    if (st === "gone") return reply({ error: "gone" }, 404);
    if (st !== "ok") return reply({ error: st || "bad request" }, st === "login" ? 401 : 400);

    // spread over the keys by how many conversations the day has had; a key that refuses hands over to the next
    let token = "", last = "";
    for (let k = 0; k < KEYS.length && !token; k++) {
      try { token = await mint(KEYS[(Number(data.n) + k) % KEYS.length], brief.instruction, style.voice); }
      catch (e) { last = String((e as Error).message || e); console.error("live-token mint failed:", last); }
    }
    tm.mint = Date.now() - t0;
    if (!token) {
      await admin.rpc("live_talk_cancel", { p_id: data.id });      // not the reader's fault: not used up
      return reply({ error: "unavailable", detail: last }, 503);
    }
    return reply({
      token, model: MODEL, lang: brief.lang, headline: brief.headline, instruction: brief.instruction,
      voice: style.voice, tools: toolsFor(NON_BLOCKING), thinking: THINKING, noise_gate: NOISE_GATE, silence_ms: SILENCE_MS, language_code: SEND_LANGUAGE_CODE ? languageCode(brief.lang, style.accent) : null,
      sentence_ids: brief.sentenceIds, max_seconds: MAX_SECONDS, hourly: HOURLY, session: data.id, timing: tm,
    });
  } catch (e) {
    return reply({ error: String((e as Error).message || e) }, 500);
  }
});
