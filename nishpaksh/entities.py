"""One identity per person in a story (Notes B1 / B2 / B18; owner, Oct 25 2026). SHADOW: nothing calls this in the
pipeline yet; `tools/entities_shadow.py` compares it with the current code on stored articles first.

Why (Group A, 14 days, 65 articles): a full name was written 3+ times in 49% of articles because `style.people` asks
"is this exact string a person, and is its surname unique among every capitalised string?" ("Parvinder Singh" and
"Parvinder Singh Jhota" are two strings, "Singh" is shared, so neither is ever shortened; a victim named only in plain
narrative has no title and no speech verb, so it is "no person evidence" 19 times); the speaker key is the SURNAME,
so Abhishek and Mamata Banerjee, Bhim Singh and DIG Harjit Singh share a key; and a speaker written with its title
("Canadian Prime Minister Mark Carney") is rejected by the person detector because the title is in the string.

An entity is a set of mentions that can only be one person. Linking is by code, precision first (a sieve):
  1. a mention is split into its title and its name (`parse`): the name is the run of capitalised words at the end,
     taken back until a title word (titles.py, the one registry) stops it;
  2. mentions with the same name (words compared through `spelling.key`: Harjit = Harjeet, Abhijeet = Abhijit) are one;
  3. a longer name absorbs a shorter one when the shorter is an ordered part of it, word by word (an initial fits a
     word that starts with it: "M K Stalin" ~ "Muthuvel Karunanidhi Stalin"); two names whose first names are both
     written out and differ are NEVER linked (the cannot-link rule that makes Bhim Singh and Harjit Singh two people);
  4. a mention that fits two different people ("Singh", "Banerjee") stays unlinked and ambiguous: a surname alone is
     only a short form of someone when exactly one person in the story has it.
A name is a person when ANY mention of the entity has evidence (a title in front, a speech verb after, being a quoted
speaker, an age beside it, a verb only a person can be the object of: "was arrested", "died"). Countries, teams,
films and schemes have none of these, so they are never shortened. Nothing here uses a model."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import spelling, titles

PARTICLES = {"al", "el", "bin", "bint", "ibn", "de", "van", "von"}
_TOKEN = re.compile(r"[A-Za-z][A-Za-z.'’-]*")
_KIN = re.compile(r"[’']s\s+(?:mother|father|wife|husband|son|daughter|brother|sister|parents|family|relatives|"
                  r"uncle|aunt|cousin|nephew|niece)\b", re.I)

SPEECH = r"(?:said|says|told|added|stated|alleged|claimed|denied|announced|noted|asked|urged|wrote|argued|replied)"
# only a person can be the object of these (a country, team, film or scheme is never "arrested"); passive or intransitive
PASSIVE = (r"(?:was|were|is|has\s+been|had\s+been|been)\s+(?:arrested|detained|killed|injured|stabbed|convicted|sentenced|"
           r"acquitted|booked|questioned|summoned|appointed|elected|sacked|hospitali[sz]ed|rescued|abducted|kidnapped|"
           r"freed|charged|rushed)")
INTRANSITIVE = r"(?:died|resigned|retired|passed\s+away|surrendered|absconded)"


def _bare(w: str) -> str:
    return w.strip(".,;:\"'‘’“”()")


def _tok_key(w: str) -> str:
    w = re.sub(r"[’']s$", "", _bare(w))
    return spelling.key(w) if len(w) >= 3 else w.lower()


def _split_initials(tokens: list[str]) -> list[str]:
    """"MK" -> "M", "K" (a run of capitals of 1-2 letters is initials); other words are kept."""
    out: list[str] = []
    for t in tokens:
        b = _bare(t).replace(".", "")
        if b.isupper() and 1 <= len(b) <= 2 and len(b) == len(re.sub(r"[^A-Za-z]", "", b)):
            out += list(b)
        else:
            out.append(b)
    return out


@dataclass(frozen=True)
class Mention:
    raw: str
    title: str          # words before the name ("Bathinda DIG"), "" when none
    tokens: tuple       # the name's words as written ("Harjit", "Singh"), possessive and bracket taken off
    kind: str           # person (a person's title is in front) | name (capitalised, no proof yet) | body | relation | role
    titled: bool        # a person title stands in front of the name

    @property
    def keys(self) -> tuple:
        return tuple(_tok_key(t) for t in self.tokens)

    @property
    def text(self) -> str:
        return " ".join(self.tokens)


def _stoppers() -> set[str]:
    return set(titles.title_words()) | set(titles.person_title_words())


def parse(raw: str) -> Mention:
    """Split what an outlet wrote into its title and its name, and say what kind of thing it names."""
    from .style import NOT_PERSON, ROLES_LOWER
    from .voice import is_body
    s = re.sub(r"\s+", " ", (raw or "").strip())
    if _KIN.search(s):
        return Mention(raw, "", (), "relation", False)
    s = re.sub(r"\s*\([^)]*\)", "", s)                  # "(CERT-In)", "(other)"
    s = s.split(",")[0].strip()                          # "Varsha Singh, a senior civil official"
    toks = _TOKEN.findall(s)
    stop = _stoppers()
    run: list[str] = []
    for t in reversed(toks):
        b = _bare(t)
        if b in stop or b.lower() in ROLES_LOWER:
            break
        if b[:1].isupper() or (b.lower() in PARTICLES and run):
            run.append(re.sub(r"[’']s$", "", b))
        else:
            break
    run.reverse()
    while run and run[0].lower() in PARTICLES:
        run.pop(0)
    prefix = toks[: len(toks) - len(run)]
    pw = set(titles.person_title_words())
    titled = any(_bare(w) in pw or _bare(w).lower() in ROLES_LOWER for w in prefix)
    title = " ".join(prefix)
    if is_body(s) or any(w in NOT_PERSON for w in run):
        return Mention(raw, title, tuple(run), "body", titled)
    if not run:
        return Mention(raw, title, (), "role", titled)
    return Mention(raw, title, tuple(run), "person" if titled else "name", titled)


def evidence_in(text: str, name: str) -> str:
    """Why `name` (a name as written in `text`) is a person: "title", "speech", "age", "passive", "apposition", "" if
    nothing in the text says so. Countries, teams, films and schemes get none of these."""
    from .style import PERSON_TITLES, ROLES_LOWER
    e = re.escape(name)
    pt = "|".join(map(re.escape, sorted(PERSON_TITLES, key=len, reverse=True)))
    rl = "|".join(sorted(ROLES_LOWER, key=len, reverse=True))
    if re.search(rf"(?:\b(?:{pt})\.?|\b(?:{rl}))\s+{e}\b", text):
        return "title"
    if re.search(rf"\b{e}\s+(?:has\s+|had\s+|also\s+|further\s+)?{SPEECH}\b", text):
        return "speech"
    if re.search(rf"\b{e},?\s*\(?\d{{1,2}}\)?[,)]", text) or re.search(rf"\b\d{{1,2}}-year-old\s+{e}\b", text) \
            or re.search(rf"\b{e},\s+an?\s+\d{{1,2}}-year-old", text):
        return "age"
    if re.search(rf"\b{e}\s+(?:{PASSIVE}|{INTRANSITIVE})\b", text):
        return "passive"
    if re.search(rf"\b{e},\s+(?:an?|the)\s+(?:[a-z-]+\s+){{0,4}}(?:{rl})\b", text):
        return "apposition"
    return ""


def _fits(a: tuple, b: tuple) -> bool:
    """Can the shorter name `a` be the same person as `b`? Every word of `a` must fit a word of `b`, in order; an
    initial fits a word that begins with it. Two written-out first names that differ never fit."""
    if not a or not b:
        return False
    a, b = _split_initials(list(a)), _split_initials(list(b))
    if len(a) > len(b):
        a, b = b, a
    ka = [_tok_key(x) if len(x) > 1 else x.lower() for x in a]
    kb = [_tok_key(x) if len(x) > 1 else x.lower() for x in b]
    j = 0
    for x in ka:
        while j < len(kb) and not (kb[j] == x or (len(x) == 1 and kb[j].startswith(x))
                                   or (len(kb[j]) == 1 and x.startswith(kb[j]))):
            j += 1
        if j == len(kb):
            return False
        j += 1
    # the surname must agree when both have more than one word: "Bhim Singh" does not fit "Harjit Singh" (first words
    # differ, so the walk above already failed); a longer name's last word is its surname
    return len(a) == 1 or ka[-1] == kb[-1] or len(ka) < len(kb) and ka == kb[: len(ka)]


@dataclass
class Entity:
    id: int
    mentions: list = field(default_factory=list)       # Mention, in the order added
    sources: set = field(default_factory=set)          # "speaker" / "text" / "statement"
    why: set = field(default_factory=set)              # evidence that it is a person
    ambiguous: bool = False                            # a lone surname that fits two or more people

    @property
    def fullest(self) -> Mention:
        # the name written out in full beats initials ("Muthuvel Karunanidhi Stalin" over "M K Stalin"), then the longer
        # name, then the one written most often
        def written(m: Mention) -> int:
            return sum(1 for t in m.tokens if len(_bare(t).replace(".", "")) > 2)
        return max(self.mentions, key=lambda m: (written(m), len(m.tokens), sum(1 for x in self.mentions if x.keys == m.keys),
                                                 -len(m.raw)))

    @property
    def person(self) -> bool:
        return bool(self.why) or any(m.titled for m in self.mentions)

    @property
    def name(self) -> str:
        return self.fullest.text

    @property
    def surname(self) -> str:
        t = self.fullest.tokens
        return t[-1] if t else ""

    @property
    def key(self) -> str:
        return ("?" if self.ambiguous else "") + " ".join(self.fullest.keys)


class EntityTable:
    """Add every mention of a story (speakers, names in the text), then ask who is who."""

    def __init__(self) -> None:
        self.mentions: list[tuple[Mention, str]] = []
        self.evidence: dict[tuple, set] = {}
        self._built = False
        self.entities: list[Entity] = []
        self._by_keys: dict[tuple, Entity] = {}
        self._by_raw: dict[str, Entity] = {}

    # ------------------------------------------------------------------ input
    def add(self, raw: str, source: str = "text", text: str = "") -> Mention:
        m = parse(raw)
        self.mentions.append((m, source))
        if m.kind in ("person", "name") and m.tokens:
            ev = self.evidence.setdefault(m.keys, set())
            if source == "speaker" and m.kind != "body":
                ev.add("speaker")
            if m.titled:
                ev.add("title")
            if text and m.text:
                w = evidence_in(text, m.text)
                if w:
                    ev.add(w)
        self._built = False
        return m

    def add_text(self, text: str) -> None:
        """Every capitalised name in a text, with the evidence the text gives for it."""
        from .style import _candidates
        for name in _candidates(text):
            self.add(name, "text", text)

    # ------------------------------------------------------------------ the sieve
    def build(self) -> "EntityTable":
        if self._built:
            return self
        people = [(m, s) for m, s in self.mentions if m.kind in ("person", "name") and m.tokens]
        self.entities, self._by_keys, self._by_raw = [], {}, {}
        # 1. the same name (by keys) is one mention-group; longest names first
        groups: dict[tuple, list] = {}
        reps: dict[tuple, tuple] = {}            # a group's name as written (initials keep their case)
        for m, s in people:
            groups.setdefault(m.keys, []).append((m, s))
            reps.setdefault(m.keys, m.tokens)
        order = sorted(groups, key=lambda k: (-len(k), k))
        multi = [k for k in order if len(k) >= 2]
        single = [k for k in order if len(k) == 1]
        clusters: list[list[tuple]] = []
        for k in multi:
            fit = [c for c in clusters if all(_fits(reps[k], reps[x]) for x in c)]
            if len(fit) == 1:
                fit[0].append(k)
            elif not fit:
                clusters.append([k])
            else:                                  # fits two people: keep it apart rather than guess
                clusters.append([k])
        # 2. a lone word joins the one person it fits; fitting two people (or none that has it) leaves it ambiguous
        extra: list[tuple] = []
        for k in single:
            fit = [c for c in clusters if any(_fits(reps[k], reps[x]) for x in c)]
            if len(fit) == 1:
                fit[0].append(k)
            else:
                extra.append((k, bool(fit)))
        for c in clusters:
            self._make([m for k in c for m in groups[k]], False)
        for k, many in extra:
            self._make(groups[k], many)
        self._built = True
        return self

    def _make(self, members: list, ambiguous: bool) -> None:
        e = Entity(id=len(self.entities) + 1, ambiguous=ambiguous)
        for m, s in members:
            e.mentions.append(m)
            e.sources.add(s)
            e.why |= self.evidence.get(m.keys, set())
            self._by_keys[m.keys] = e
            self._by_raw[m.raw] = e
        self.entities.append(e)

    # ------------------------------------------------------------------ output
    def entity(self, raw: str) -> Entity | None:
        self.build()
        m = parse(raw)
        return self._by_keys.get(m.keys) if m.tokens else None

    def speaker_key(self, raw: str) -> str | None:
        """One key per speaker: the entity for a person, the old key for bodies and anything else."""
        from .voice import speaker_key as old
        e = self.entity(raw)
        if e is not None and e.person and not e.ambiguous:
            return e.key
        return old(raw)

    def persons(self) -> list[Entity]:
        self.build()
        return [e for e in self.entities if e.person]

    def shortenable(self) -> dict[str, str]:
        """{full name: surname} for every written form of a person who can be called by surname without confusion:
        the entity is a person and its surname is no other person's surname or first name in the story."""
        self.build()
        persons = self.persons()
        out: dict[str, str] = {}
        for e in persons:
            if e.ambiguous or len(e.fullest.tokens) < 2:
                continue
            sk = _tok_key(e.surname)
            # a surname that is any word of another name in the story ("Singh" is Parvinder Singh's middle name,
            # "Mohan" is someone's first name) is no short form
            if any(sk in {k for m in o.mentions for k in m.keys} for o in self.entities if o is not e):
                continue
            for m in e.mentions:
                if len(m.tokens) >= 2:
                    out[m.text] = e.surname
        return out
