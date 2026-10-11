// How the guide SOUNDS (owner, Oct 11 2026: "give the options to the user; the default is how an Indian speaks").
//
// Pure code, no Deno or network in it, tested with node (tests/live/voice.test.mjs). The reader's choices arrive from the
// browser, so nothing here trusts them: every field is checked against a fixed list and falls back to the default, and the
// text that reaches the model is written HERE from those lists, never copied from the request.
//
// What Gemini's Live API really offers: a voice (`voiceName`, 30 of them; the 10 below are the ones Google's docs list with
// a descriptor) and a language code. It has no speed, accent or tone setting, so those three are asked for in words in the
// instruction (and can be asked again mid-conversation). How well a voice follows them is for the ear to judge.

export const VOICES = ["Kore", "Orus", "Zephyr", "Autonoe", "Umbriel", "Erinome", "Laomedeia", "Schedar", "Achird", "Sadachbia"] as const;
export const PACES = ["slow", "natural", "fast"] as const;
export const TONES = ["warm", "news"] as const;
export const ACCENTS = ["indian", "neutral"] as const;

export type Style = { voice: (typeof VOICES)[number]; pace: (typeof PACES)[number]; tone: (typeof TONES)[number]; accent: (typeof ACCENTS)[number] };

/** Kore is what the guide has used so far. Natural pace, a warm tone, Indian English: how an educated Indian explains the news to a friend. */
export const DEFAULT_STYLE: Style = { voice: "Kore", pace: "natural", tone: "warm", accent: "indian" };

const pick = <T extends string>(list: readonly T[], v: unknown, d: T): T => typeof v === "string" && (list as readonly string[]).includes(v) ? (v as T) : d;   // a string only: ["indian"] must not pass

/** Whatever the browser sent, as a safe style: unknown or missing fields take the default. */
export function cleanStyle(raw: unknown): Style {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  return {
    voice: pick(VOICES, r.voice, DEFAULT_STYLE.voice),
    pace: pick(PACES, r.pace, DEFAULT_STYLE.pace),
    tone: pick(TONES, r.tone, DEFAULT_STYLE.tone),
    accent: pick(ACCENTS, r.accent, DEFAULT_STYLE.accent),
  };
}

/** The BCP-47 code for the language setting: Hindi, Indian English or neutral (US) English. Only sent to Gemini when the
 *  function's LIVE_LANGUAGE_CODE secret is "1": native-audio models choose the language themselves and may refuse it. */
export function languageCode(lang: string, accent: Style["accent"]): string {
  return lang === "hi" ? "hi-IN" : accent === "neutral" ? "en-US" : "en-IN";
}

const PACE: Record<Style["pace"], string> = {
  slow: "Speak slowly and clearly, with a short pause between sentences, as you would to someone on a noisy phone line.",
  natural: "Speak at a natural, unhurried conversational pace, a little more measured than casual chat because this is news. Pause briefly between ideas.",
  fast: "Speak briskly, like a busy newsroom, but never run words together and never skip a name or a number.",
};
const TONE: Record<Style["tone"], string> = {
  warm: "Sound warm, friendly and calm, like a knowledgeable friend explaining the news over chai. Never dramatic, never salesy.",
  news: "Sound neutral, steady and even, like a newsreader. No enthusiasm, no exclamations.",
};
const ACCENT: Record<Style["accent"], string> = {
  indian: "When you speak English, use Indian English: Indian pronunciation, rhythm and intonation, as a well-educated Indian speaker has.",
  neutral: "When you speak English, use a neutral, international English accent that is easy for anyone to follow.",
};

/** The manner block that goes into the instruction. The first part (how an Indian listener expects to hear it) is the same
 *  for everyone; the three lines after it are the reader's choices. Nothing here can loosen the rules about the article. */
export function voiceBlock(s: Style): string {
  return [
    "HOW YOUR VOICE SOUNDS (this changes how you sound, never what you may say: the rules above stay as they are)",
    "- You are talking to a reader in India. Say Indian names, places, parties and institutions the way people in India say them.",
    "- Say amounts as Indians do: lakh and crore, rupees. Say \"40 crore rupees\", never convert to millions or dollars.",
    "- In Hindi, speak natural everyday Hindi as it is spoken in north India, not bookish or heavily Sanskritised. Common English words (court, minister, police, election) are said the way people say them in Hindi conversation. If the reader mixes Hindi and English, you may mix the same way.",
    `- ${ACCENT[s.accent]}`,
    `- ${PACE[s.pace]}`,
    `- ${TONE[s.tone]}`,
    "- Whatever the tone, stay gentle and serious when the story is about deaths, violence or suffering.",
    "- If the reader asks you to speak slower, faster or differently, do it right away, then carry on.",
  ].join("\n");
}
