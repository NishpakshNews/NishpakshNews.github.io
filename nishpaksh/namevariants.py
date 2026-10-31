"""Name variants: one name written two ways in two statements of one story (SHADOW; nothing calls this module).

Seen on a published article (story 48298, 31 Oct 2026): "Gujarat Animal Preservation Act" and "Gujarat Animal Conservation Act"
stood as two background lines because every word rule reads a capitalised word that differs on BOTH sides as two different
things (relate.name_sets_fit), which is right for two people and wrong for one name translated twice. 35% of the sentences on
the site rest on Hindi-only sources, so the same Hindi name reaches English in several spellings.

The rule behind it (owner): code proposes, a model only confirms; any doubt leaves the pair as it is. This module therefore
never merges anything. `decide` returns one of
    same    code evidence says the slot is one name written two ways  -> the caller still asks the reader twice
    ask     a translated TERM differs (no transliteration explains it) -> only the reader / a cross-lingual check can say
    apart   the Hindi source explains exactly one of the two words   -> evidence they are two names, never offered again
    unsure  anything else (more than one slot, no evidence)         -> nothing changes, as today
No word lists. The evidence, by case of the sources behind the two lines:
    Hindi only     the same Devanagari gives one English rendering (TermMemory: the source's own bracketed English first);
                   a Devanagari word left inside an English line is rendered, not kept (`fix_leak`)
    Hindi + English the English outlets' spelling is the display form (`choose_form`)
    English only   a one-word spelling difference, the rest of the sentence identical, character similarity >= SPELLING_MIN
Stdlib only, so it is testable without models. Thresholds are UNTUNED guesses to be read in the audit (see THRESHOLDS).
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter

SPELLING_MIN = 0.80      # character similarity of two Latin slots that count as one name spelt twice (measured: 2/6 variants, 0/30 false)
EXPLAIN_MIN = 0.75       # skeleton similarity of a Latin slot and the transliteration of a Devanagari word that "explains" it
MAX_SLOT = 3             # words in the differing slot, each side
MIN_WORDS = 5            # a pair shorter than this has too little around the slot to say it is the same sentence
THRESHOLDS = {"SPELLING_MIN": SPELLING_MIN, "EXPLAIN_MIN": EXPLAIN_MIN, "MAX_SLOT": MAX_SLOT, "MIN_WORDS": MIN_WORDS}

DEV = re.compile(r"[ऀ-ॿ]")
_WORD = re.compile(r"[\wऀ-ॿ'’-]+")
_DEV_RUN = r"[ऀ-ॿ]+(?:[ ‌‍]+[ऀ-ॿ]+)*"
_LAT_PHRASE = r"[A-Za-z][A-Za-z .'’-]{2,60}"
_BRACKET = [re.compile(rf"({_DEV_RUN})\s*\(\s*({_LAT_PHRASE}?)\s*\)"), re.compile(rf"({_LAT_PHRASE}?)\s*\(\s*({_DEV_RUN})\s*\)")]


# --- Devanagari helpers -----------------------------------------------------------------------------------------------

def deva_key(text: str) -> str:
    """A Devanagari string as a comparison key: NFC, no zero-width joiners, no nukta, single spaces, no punctuation."""
    t = unicodedata.normalize("NFD", text or "")
    t = t.replace("‌", "").replace("‍", "").replace("़", "")
    t = unicodedata.normalize("NFC", t)
    return " ".join(w for w in re.findall(r"[ऀ-ॿ]+", t))


def deva_tokens(text: str) -> list[str]:
    return deva_key(text).split()


_CONS = {"क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n", "ट": "t",
         "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p", "फ": "ph",
         "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h"}
_VOWEL = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au"}
_MATRA = {"ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au"}


def transliterate(word: str) -> str:
    """Devanagari to Latin by sound (deterministic, no model); a word-final inherent 'a' is dropped, as Hindi does."""
    w = deva_key(word).replace(" ", "")
    out: list[str] = []
    i = 0
    while i < len(w):
        c = w[i]
        if c in _CONS:
            out.append(_CONS[c])
            nxt = w[i + 1] if i + 1 < len(w) else ""
            if nxt in _MATRA:
                out.append(_MATRA[nxt]); i += 2; continue
            if nxt == "्":                      # virama: no vowel
                i += 2; continue
            out.append("a" if i + 1 < len(w) else "")  # inherent vowel, dropped at the end of the word
        elif c in _VOWEL:
            out.append(_VOWEL[c])
        elif c in "ंँ":
            out.append("n")
        elif c == "ः":
            out.append("h")
        i += 1
    return "".join(out)


def skeleton(latin: str) -> str:
    """Consonant skeleton of a Latin word: robust to the vowel spellings that differ between transliterations."""
    t = re.sub(r"[^a-z]", "", (latin or "").lower().replace("w", "v").replace("ph", "f"))
    t = re.sub(r"(.)\1+", r"\1", t)
    s = re.sub(r"[aeiouy]", "", t)
    return s or t


def char_sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, re.sub(r"\W", "", a.lower()), re.sub(r"\W", "", b.lower())).ratio()


def explains(slot_words: list[str], hindi_source: str) -> bool:
    """Does some Devanagari word of the Hindi source, written in Latin letters, sound like this slot? (a transliterated NAME)"""
    sk = skeleton("".join(slot_words))
    if not sk:
        return False
    toks = deva_tokens(hindi_source)
    # single words and neighbouring pairs (a two-word name is one slot)
    cands = toks + [a + b for a, b in zip(toks, toks[1:])]
    return any(difflib.SequenceMatcher(None, sk, skeleton(transliterate(c))).ratio() >= EXPLAIN_MIN for c in cands if c)


# --- what the source says in English: bracketed forms and the term memory ------------------------------------------------

def bracket_pairs(text: str) -> list[tuple[str, str]]:
    """(Devanagari key, English) where a Hindi article writes the English name itself: 'अमर प्रीत सिंह ( IAF Chief Amarpreet Singh )'."""
    out = []
    for m in _BRACKET[0].finditer(text or ""):
        out.append((deva_key(m.group(1)), m.group(2).strip()))
    for m in _BRACKET[1].finditer(text or ""):
        out.append((deva_key(m.group(2)), m.group(1).strip()))
    return [(d, e) for d, e in out if d and e]


RANK_BRACKET, RANK_REGISTRY, RANK_MAJORITY, RANK_SOUND = 3, 2, 1, 0


class TermMemory:
    """One English rendering per Devanagari name (a term base, as translation tools keep): the same Devanagari, the same English."""

    def __init__(self) -> None:
        self.forms: dict[str, Counter] = {}

    def learn(self, deva: str, english: str, rank: int = RANK_MAJORITY) -> None:
        k = deva_key(deva)
        if k and english:
            self.forms.setdefault(k, Counter())[(rank, english.strip())] += 1

    def learn_source(self, source_text: str) -> int:
        n = 0
        for d, e in bracket_pairs(source_text):
            self.learn(d, e, RANK_BRACKET); n += 1
        return n

    def render(self, deva: str) -> tuple[str, int] | None:
        c = self.forms.get(deva_key(deva))
        if not c:
            return None
        (rank, form), _n = max(c.items(), key=lambda kv: (kv[0][0], kv[1], len(kv[0][1])))
        return form, rank

    def fix_leak(self, english_text: str) -> tuple[str, list[dict]]:
        """A Devanagari word left inside an English line becomes its learned rendering, else its sound in Latin letters."""
        done: list[dict] = []

        def sub(m: re.Match) -> str:
            run = m.group(0)
            got = self.render(run)
            if got:
                new, rank = got
            else:
                new, rank = transliterate(run), RANK_SOUND
            new = new[:1].upper() + new[1:] if new and not got else new
            done.append({"from": run, "to": new, "rank": rank})
            return new
        return re.sub(_DEV_RUN, sub, english_text or ""), done


# --- the pair ------------------------------------------------------------------------------------------------------------

def slot_diff(a: str, b: str):
    """(slot words of a, slot words of b) when the two lines differ in exactly ONE contiguous place of at most MAX_SLOT words."""
    ta, tb = _WORD.findall(a or ""), _WORD.findall(b or "")
    if min(len(ta), len(tb)) < MIN_WORDS:
        return None
    sm = difflib.SequenceMatcher(None, [w.lower() for w in ta], [w.lower() for w in tb], autojunk=False)
    ops = [o for o in sm.get_opcodes() if o[0] != "equal"]
    if len(ops) != 1 or ops[0][0] != "replace":
        return None
    _t, i1, i2, j1, j2 = ops[0]
    if i2 - i1 > MAX_SLOT or j2 - j1 > MAX_SLOT:
        return None
    sa, sb = ta[i1:i2], tb[j1:j2]
    if all(re.fullmatch(r"[\d.,%]+", w) for w in sa + sb):      # figures are the figure rules' business
        return None
    return sa, sb


def choose_form(forms: dict[str, list[dict]]) -> str | None:
    """The display form: the one written by the most DISTINCT English outlets (the original wording, not a translation).
    `forms` = {form: its backing}. A tie, or no English outlet behind any form, is None: both stay as variants."""
    score = {f: len({b.get("outlet") for b in back if b.get("lang") == "en"}) for f, back in forms.items()}
    best = max(score.values(), default=0)
    top = [f for f, s in score.items() if s == best]
    return top[0] if best > 0 and len(top) == 1 else None


def decide(a: str, b: str, backing_a=(), backing_b=()) -> dict:
    """Judge ONE pair of statements of a story. backing_*: [{"lang": "hi"|"en", "outlet": str, "src": the report's own sentence}]."""
    d = slot_diff(a, b)
    if d is None:
        return {"verdict": "unsure", "route": "not-one-slot", "why": "the lines differ in more than one place"}
    sa, sb = d
    out = {"slot": [" ".join(sa), " ".join(sb)]}
    da, db = any(DEV.search(w) for w in sa), any(DEV.search(w) for w in sb)
    # a Devanagari word left in an English line
    if da != db:
        deva, lat = (sa, sb) if da else (sb, sa)
        if difflib.SequenceMatcher(None, skeleton(transliterate(" ".join(deva))), skeleton(" ".join(lat))).ratio() >= EXPLAIN_MIN:
            return {**out, "verdict": "same", "route": "leak", "canonical": " ".join(lat),
                    "why": "the Devanagari word left in the English line sounds like the other line's spelling"}
        return {**out, "verdict": "unsure", "route": "leak", "why": "the Devanagari word does not sound like the other spelling"}
    if da and db:
        same = deva_key(" ".join(sa)) == deva_key(" ".join(sb))
        return {**out, "verdict": "same" if same else "unsure", "route": "devanagari", "why": "the same Devanagari" if same else "other Devanagari"}
    # both Latin: what the Hindi sources say decides first
    src_a = " ".join(x.get("src", "") for x in backing_a if x.get("lang") == "hi")
    src_b = " ".join(x.get("src", "") for x in backing_b if x.get("lang") == "hi")
    hindi = (src_a + " " + src_b).strip()
    if hindi and (src_a or src_b):
        ea, eb = explains(sa, hindi), explains(sb, hindi)
        if ea != eb:
            return {**out, "verdict": "apart", "route": "transliteration",
                    "why": "the Hindi source sounds like one slot only: two different names"}
        if ea and eb:
            return {**out, "verdict": "same", "route": "transliteration", "why": "the Hindi source sounds like both slots"}
        if char_sim(" ".join(sa), " ".join(sb)) < SPELLING_MIN:
            return {**out, "verdict": "ask", "route": "term",
                    "why": "no transliteration explains either slot: a translated term, only the reader can say"}
    s = char_sim(" ".join(sa), " ".join(sb))
    if s >= SPELLING_MIN:
        return {**out, "verdict": "same", "route": "spelling", "similarity": round(s, 2),
                "why": "one spelling difference, the rest identical"}
    return {**out, "verdict": "unsure", "route": "spelling", "similarity": round(s, 2), "why": "too different to call one name"}
