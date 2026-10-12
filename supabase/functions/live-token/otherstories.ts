// The other stories of today, as a short list for the ARTICLE guide (owner, Oct 13 2026): so that, when the reader asks about another story
// ("what about the court order?", "anything else on this today?"), the guide knows which stories exist and can open one with open_article
// (its full text comes back from this same function). One line a story, newest first: [a<story id>] how long ago | outlets | headline.
// The recap guide does not need this list: its own lines already carry every story's number (s<story id>).
//
// Pure code, no Deno or network in it, tested with node (tests/live/otherstories.test.mjs). The data is the site's own feed file (the cards it shows).

import { clean } from "./brief.ts";

export type FeedCard = { id?: number | string; at?: string; h?: string; n?: number; paras?: { t?: string; c?: string }[][] };
export type Feed = { generated_at?: string; stories?: FeedCard[] };

export const MAX_OTHER = 40;           // a day has 20-60 stories; the newest 40 are listed (each line is short)
const MIN_TODAY = 5;                   // fewer than this on the IST day (early morning): the last 24 hours are used instead
const IST_MS = 19_800_000;             // IST is UTC+5:30 all year

/** The feed writes times as UTC without a zone ("2026-10-13T08:05:00"): read them as UTC. NaN when it is not a time. */
export function utcMs(at: string | undefined): number {
  const s = clean(at);
  if (!s) return NaN;
  return Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`);
}
const istDay = (ms: number) => new Date(ms + IST_MS).toISOString().slice(0, 10);

/** "12 minutes ago" / "3 hours ago" (and in Hindi). */
export function agoWords(ms: number, now: number, lang: "en" | "hi"): string {
  const min = Math.max(0, Math.round((now - ms) / 60_000));
  if (min < 2) return lang === "hi" ? "अभी-अभी" : "just now";
  if (min < 60) return lang === "hi" ? `${min} मिनट पहले` : `${min} minutes ago`;
  const h = Math.round(min / 60);
  return lang === "hi" ? `${h} घंटे पहले` : `${h} ${h === 1 ? "hour" : "hours"} ago`;
}

/** Today's cards, newest first: the IST day of `now`; when that has fewer than MIN_TODAY, the last 24 hours. Cards without a time, a
 *  headline or a sentence are left out. */
export function todaysCards(feed: Feed, now: number): { card: FeedCard; at: number }[] {
  const all = (feed.stories || [])
    .map((card) => ({ card, at: utcMs(card?.at) }))
    .filter((x) => x.card && x.card.id !== undefined && x.card.id !== null && Number.isFinite(x.at) && x.at <= now + 3_600_000 && clean(x.card.h)
      && (x.card.paras || []).some((p) => (p || []).some((s) => clean(s?.t))))
    .sort((a, b) => b.at - a.at);
  const day = istDay(now);
  const today = all.filter((x) => istDay(x.at) === day);
  return today.length >= MIN_TODAY ? today : all.filter((x) => now - x.at <= 24 * 3_600_000);
}

/** The lines of the OTHER stories block (without the story the reader is on). [] when the feed is missing or has nothing else. */
export function otherStories(feed: Feed | null | undefined, lang: "en" | "hi", exceptId: number | string, now: number = Date.now()): string[] {
  if (!feed || !Array.isArray(feed.stories)) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const { card, at } of todaysCards(feed, now)) {
    const id = String(card.id);
    if (id === String(exceptId) || seen.has(id)) continue;
    seen.add(id);
    const n = Number.isFinite(card.n) && (card.n as number) > 0 ? (card.n as number) : 0;
    const outlets = n ? (lang === "hi" ? `${n} स्रोत` : `${n} ${n === 1 ? "outlet" : "outlets"}`) : "";
    out.push(`[a${id}] ${[agoWords(at, now, lang), outlets, clean(card.h)].filter(Boolean).join(" | ")}`);
    if (out.length >= MAX_OTHER) break;
  }
  return out;
}
