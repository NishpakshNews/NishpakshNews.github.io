// "Talk to the article": the door to a live voice conversation (owner, Oct 11 2026).
//
// The browser talks to Gemini's Live API directly (one WebSocket, no proxy), but never holds a Gemini key. It asks
// here first. This function: (1) checks the reader is logged in, (2) asks the database whether they may start one
// (live_talk_begin: a few a day each, and a cap on how many run at the same moment across the site), (3) reads the
// article from the feed branch and builds what the model may use (brief.ts), (4) asks Gemini for a ONE-USE token that
// is locked to the Live model and to that instruction, and expires when the longest allowed conversation does, and
// (5) hands the browser the token, the instruction (so it can repeat it in its setup message), and the ids of the
// sentences the model may light up.
//
// Deployed with verify_jwt off, like `account`: the site calls it with the publishable key, and the reader's own
// access token is checked here. Secrets: GEMINI_API_KEY, GEMINI_API_KEY_2, ... (the same keys the pipeline uses;
// each from its own project, so conversations are spread over them). Optional: LIVE_MODEL, FEED_URL, LIVE_LANGUAGE_CODE=1
// (also send a language code to Gemini; off by default). The request may carry `style` {voice, pace, tone, accent}.
import { createClient } from "npm:@supabase/supabase-js@2.45.4";
import { articleDigest, buildBrief, TOOLS, type Other, type Story } from "./brief.ts";
import { cleanStyle, languageCode } from "./voice.ts";

const URL_ = Deno.env.get("SUPABASE_URL")!;
const SERVICE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const admin = createClient(URL_, SERVICE, { auth: { persistSession: false, autoRefreshToken: false } });

const MODEL = Deno.env.get("LIVE_MODEL") || "gemini-3.8-live";
const SEND_LANGUAGE_CODE = Deno.env.get("LIVE_LANGUAGE_CODE") === "1";   // see voice.ts: off until the model is known to accept it
const FEED_URL = Deno.env.get("FEED_URL") || "https://raw.githubusercontent.com/NishpakshNews/NishpakshNews.github.io/feed";
const KEYS = [...new Set(["GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY_4", "GEMINI_API_KEY_5"]
  .map((k) => (Deno.env.get(k) || "").trim()).filter(Boolean))];

const DAILY = 3;               // conversations per reader per IST day
const CONCURRENT = Number(Deno.env.get("LIVE_CONCURRENT")) || 3;   // at the same moment, whole site; a guess to be tuned (Gemini 3.8 Live: 65K tokens a minute per project). Set the secret LIVE_CONCURRENT to change it
const MAX_SECONDS = 480;       // the longest conversation: the token itself expires then
const GEMINI = "https://generativelanguage.googleapis.com/v1beta/auth_tokens";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
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
        },
        systemInstruction: { parts: [{ text: instruction }] },
        tools: TOOLS,
        inputAudioTranscription: {},
        outputAudioTranscription: {},
        realtimeInputConfig: { automaticActivityDetection: { silenceDurationMs: 700, prefixPaddingMs: 100 } },
      },
    }),
  });
  if (!r.ok) throw new Error(`gemini ${r.status}: ${(await r.text()).slice(0, 700)}`);
  const j = await r.json();
  if (!j?.name) throw new Error("gemini sent no token");
  return String(j.name);
}

// the other live articles (headline and id), for the guide's list; nothing is counted against anyone when this fails
async function others(lang: string): Promise<Other[]> {
  try {
    const r = await fetch(`${FEED_URL}/${lang}.json`, { signal: AbortSignal.timeout(4000) });
    if (!r.ok) return [];
    const j = await r.json();
    return (Array.isArray(j?.stories) ? j.stories : [])
      .filter((c: { id?: unknown; h?: unknown }) => Number.isInteger(c?.id) && typeof c?.h === "string" && c.h.trim())
      .map((c: { id: number; h: string }) => ({ id: c.id, headline: c.h }));
  } catch { return []; }
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return reply({ error: "POST only" }, 405);
  let b: Record<string, unknown> = {};
  try { b = await req.json(); } catch { return reply({ error: "bad request" }, 400); }
  const lang = b.lang === "hi" ? "hi" : "en";

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

  // the guide asked to read another article (the function read_article): no limit is used, the reader must be logged in
  if (b.read !== undefined) {
    const id = Number(b.read);
    if (!Number.isInteger(id) || id < 1) return reply({ error: "bad request" }, 400);
    try {
      if (!(await me(req))) return reply({ error: "login" }, 401);
      const page = await fetch(`${FEED_URL}/story/${id}.json`);
      if (!page.ok) return reply({ error: "gone" }, 404);
      const d = articleDigest((await page.json()) as Story, lang);
      return d ? reply(d) : reply({ error: "gone" }, 404);
    } catch (e) { return reply({ error: String((e as Error).message || e) }, 500); }
  }

  const story = Number(b.story_id);
  if (!Number.isInteger(story) || story < 1) return reply({ error: "bad request" }, 400);
  if (!KEYS.length) return reply({ error: "not configured" }, 500);

  try {
    const user = await me(req);
    if (!user) return reply({ error: "login" }, 401);

    // the article first: nothing is counted against the reader when there is nothing to talk about
    const page = await fetch(`${FEED_URL}/story/${story}.json`);
    if (!page.ok) return reply({ error: "gone" }, 404);
    const style = cleanStyle(b.style);                  // the reader's voice, pace, tone and accent: checked against fixed lists
    const brief = buildBrief((await page.json()) as Story, lang, style, await others(lang));
    if (!brief) return reply({ error: "gone" }, 404);

    const { data, error } = await admin.rpc("live_talk_begin", {
      p_reader: user.id, p_story: story, p_lang: brief.lang, p_daily: DAILY, p_concurrent: CONCURRENT, p_seconds: MAX_SECONDS,
    });
    if (error) return reply({ error: error.message }, 500);
    const st = String(data?.status || "");
    if (st === "limit") return reply({ error: "limit", daily: DAILY }, 429);
    if (st === "busy") return reply({ error: "busy" }, 503);
    if (st === "gone") return reply({ error: "gone" }, 404);
    if (st !== "ok") return reply({ error: st || "bad request" }, st === "login" ? 401 : 400);

    // spread over the keys by how many conversations the day has had; a key that refuses hands over to the next
    let token = "", last = "";
    for (let k = 0; k < KEYS.length && !token; k++) {
      try { token = await mint(KEYS[(Number(data.n) + k) % KEYS.length], brief.instruction, style.voice); }
      catch (e) { last = String((e as Error).message || e); console.error("live-token mint failed:", last); }
    }
    if (!token) {
      await admin.rpc("live_talk_cancel", { p_id: data.id });      // not the reader's fault: not used up
      return reply({ error: "unavailable", detail: last }, 503);
    }
    return reply({
      token, model: MODEL, lang: brief.lang, headline: brief.headline, instruction: brief.instruction,
      voice: style.voice, language_code: SEND_LANGUAGE_CODE ? languageCode(brief.lang, style.accent) : null,
      sentence_ids: brief.sentenceIds, max_seconds: MAX_SECONDS, daily: DAILY, session: data.id,
    });
  } catch (e) {
    return reply({ error: String((e as Error).message || e) }, 500);
  }
});
