"""Context for everything the learners learn (owner, Oct 16 2026): a word is learned IN A CONTEXT, never alone.

"Bank" is a financial bank, the bank of a river, the bank of a road. "Charge" is an allegation in a court story and
a fee in a business story. "Captain" is a cricket role, an Army rank and a pilot. Counting how often a word repeats
adds its senses together, so one sense wins everywhere or the senses look like rivals. Here a sighting carries its
context, sightings are grouped into SENSES, and an entry is applied only where its context matches.

THE CONTEXT OF A SIGHTING, precisely:
  section  the story's secondary section (elections, courts, markets ...), else its primary one (categories.py),
           else "" (a story gets its section when it is published: before that, while articles are read and matched,
           the section is unknown);
  words    the content words of the sentence it stood in: lower case, stemmed (English) or folded (Hindi), with stop
           words, numbers, names (capitalised in English) and the word itself removed. "Villages on the bank of the
           Kosi were flooded" -> {villag, flood} ("Kosi" is a name).

A SENSE is a section and a signature: the context words its sightings keep repeating, with counts.
  JOIN     (generous) a sighting joins the senses of its section with which it shares any word, and joins two
           such senses into one when it shares words with both; with an unknown section it needs STRICT_WORDS (3)
           signature words. Otherwise it starts a new sense.
  SIGNATURE  the words seen in at least 2 of the sense's sightings; while the sense has fewer than 3 sightings,
           all its words.
  MATCH    (strict) a new sentence uses the sense of its section sharing the most signature words, if it shares at least
           JOIN_WORDS and strictly more than any other sense (STRICT_WORDS when the section is unknown). No match:
           nothing stored is used (the owner: a new context never borrows another context's entry).
  TEMPORARY  when nothing matches and a model supplies the answer (a translation), it may be saved as a temporary
           sense with that sentence's context, replaced once outlets give real evidence for that context.

Pure code over plain values; the learners (learn_*.py) keep each sense as one candidate in their memory.
"""
from __future__ import annotations

import dataclasses
import re

JOIN_WORDS = 2
STRICT_WORDS = 3
SIGNATURE_MIN = 2           # sightings a word must appear in to be part of the signature
YOUNG = 3                   # a sense with fewer sightings uses all its words as its signature
MAX_WORDS = 60              # signature words kept per sense

_EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z'-]*")
_HI_TOKEN = re.compile(r"[ऀ-ॣ॰-ॿ‌‍]{2,}")

_HI_STOP = set("""है हैं था थे थी हो होने होगा होगी की का के को में से ने और पर यह वह इस उस इन उन ये वे कि भी तो ही लिए
गया गई गए किया कर करने करते करता करती रहा रही रहे एक जो अपने अपनी अपना बताया कहा साथ बाद तक अब नहीं लेकिन या
जब तब यहां वहां कोई कुछ सभी बहुत दिया दी दिए लेकर बीच दौरान वाले वाली वाला ओर द्वारा इसके उसके उनके इसकी उसकी
उनकी जा सकता सकती सकते रूप तरह हुए हुई हुआ हुईं होते होती होता गयी गये रहें दें लिया ली लिये""".split())


def _en_stop() -> set[str]:
    from .frames import STOP
    return set(STOP) | {"said", "says", "say", "told", "also", "will", "would", "could", "should", "may", "might",
                        "been", "being", "have", "has", "had", "not", "after", "before", "over", "into", "were",
                        "was", "are", "is", "be", "on", "in", "at", "to", "for", "with", "by", "from", "and", "or"}


def section_of(category: dict | None) -> str:
    """The story's context section: its first secondary section, else its first primary one, else ""."""
    c = category or {}
    for level in ("secondary", "primary"):
        keys = c.get(level) or []
        if keys:
            return str(keys[0])
    return ""


def words(sentence: str, lang: str, exclude: str | set[str] = "") -> frozenset[str]:
    """The content words of a sentence, as compared: English lower case and stemmed, names (capitalised mid-sentence)
    and numbers out; Hindi folded (names.fold_hi). `exclude`: the word(s) the context is for, left out."""
    ex = {exclude} if isinstance(exclude, str) else set(exclude)
    if lang == "hi":
        from .names import fold_hi
        exf = {fold_hi(e) for e in ex if e}
        return frozenset(fold_hi(w) for w in _HI_TOKEN.findall(sentence or "")
                         if w not in _HI_STOP and fold_hi(w) not in exf)
    from .frames import _stem
    stop = _en_stop()
    exs = {_stem(e.lower()) for e in ex if e}
    out = set()
    for k, m in enumerate(_EN_TOKEN.finditer(sentence or "")):
        w = m.group(0)
        if k > 0 and w[0].isupper():
            continue                                   # a name, mid-sentence
        lw = w.lower().strip("'-")
        if len(lw) < 3 or lw in stop:
            continue
        s = _stem(lw)
        if s not in exs:
            out.add(s)
    return frozenset(out)


@dataclasses.dataclass
class Sense:
    """One sense of an entry: its section, how many sightings it has, and its context words with counts."""
    section: str = ""
    sightings: int = 0
    counts: dict = dataclasses.field(default_factory=dict)

    def signature(self) -> set[str]:
        if self.sightings < YOUNG:
            return set(self.counts)
        return {w for w, n in self.counts.items() if n >= SIGNATURE_MIN}

    def add(self, ws) -> None:
        self.sightings += 1
        for w in ws:
            self.counts[w] = self.counts.get(w, 0) + 1
        if len(self.counts) > MAX_WORDS:            # keep the most repeated words
            keep = sorted(self.counts.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_WORDS]
            self.counts = dict(keep)

    def to_dict(self) -> dict:
        return {"section": self.section, "sightings": self.sightings, "counts": self.counts}

    @classmethod
    def from_dict(cls, d: dict | None) -> "Sense":
        d = d or {}
        return cls(str(d.get("section") or ""), int(d.get("sightings") or 0), dict(d.get("counts") or {}))


def _need(a: str, b: str) -> int:
    return STRICT_WORDS if not a or not b else JOIN_WORDS


def _fits(sense: Sense, section: str, ws) -> int:
    """How many signature words the context shares with the sense; 0 when the section rules it out."""
    if sense.section and section and sense.section != section:
        return 0
    return len(sense.signature() & set(ws))


def best(senses: dict, section: str, ws) -> str | None:
    """The key of the sense a context belongs to: the most shared signature words, at least the threshold, strictly
    more than any other sense. None: no sense fits (or two fit equally)."""
    scored = []
    for key, s in senses.items():
        n = _fits(s, section, ws)
        if n >= _need(s.section, section):
            scored.append((n, key))
    if not scored:
        return None
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def assign(senses: dict, section: str, ws, new_key) -> str:
    """The sense a sighting joins (or a new one, keyed `new_key()`), updated with the sighting's words. `senses`:
    {key: Sense}, changed in place.

    Known section: the sighting joins the senses of that section with which it shares ANY word (all their words,
    not only the signature: a section already separates most senses, and ordinary sentences about a bank share
    few words); a sighting that shares words with two such senses joins them into one (it shows they are one).
    Unknown section, or senses first seen with an unknown one: STRICT_WORDS signature words. Otherwise a new sense.
    Joining is generous; USING an entry (`best`) stays strict."""
    ws = set(ws)
    key = None
    if section:
        near = [k for k, s in senses.items() if s.section == section and set(s.counts) & ws]
        if near:
            near.sort(key=lambda k: (-senses[k].sightings, k))
            key = near[0]
            for other in near[1:]:                     # a bridge: two senses of one section are one
                o = senses.pop(other)
                senses[key].sightings += o.sightings
                for w, n in o.counts.items():
                    senses[key].counts[w] = senses[key].counts.get(w, 0) + n
        else:
            loose = [(len(s.signature() & ws), k) for k, s in senses.items() if not s.section]
            loose = [x for x in loose if x[0] >= STRICT_WORDS]
            if loose:
                key = max(loose)[1]
    else:
        key = best(senses, "", ws)
    if key is None:
        key = new_key()
        senses[key] = Sense(section)
    s = senses[key]
    if not s.section and section:
        s.section = section                           # a sense first seen before publication takes its section
    s.add(ws)
    return key


def story_sections(store, story_ids) -> dict:
    """{story id: context section} for the stories that have been published (others have none yet)."""
    ids = sorted({s for s in story_ids if s is not None})
    if not ids:
        return {}
    from sqlalchemy import select
    from .db import published
    out = {}
    for start in range(0, len(ids), 400):
        for r in store.rows(select(published.c.story_id, published.c.payload_en["category"].label("category"))
                            .where(published.c.story_id.in_(ids[start:start + 400]))):
            cat = r.get("category")
            if isinstance(cat, str):
                import json
                try:
                    cat = json.loads(cat)
                except ValueError:
                    cat = None
            out[r["story_id"]] = section_of(cat if isinstance(cat, dict) else None)
    return out


def sentence_with(text: str, word: str, lang: str) -> str:
    """The sentence of a text in which `word` stands (whole word), or ""."""
    from .fidelity import sentences
    if lang == "hi":
        pat = re.compile(rf"(?<![ऀ-ॿ]){re.escape(word)}(?![ऀ-ॿ])")
    else:
        pat = re.compile(rf"(?<![\w-]){re.escape(word)}(?![\w-])", re.I)
    for s in sentences(text or ""):
        if pat.search(s):
            return s
    return ""
