"""One identity per person in a story (Notes B1 / B2 / B18; owner, Oct 25 2026).

Who is a person comes from named-entity recognition (nlp.py, spaCy), not from word lists: a name is a person when the
analyser labels it PERSON in the article (or it is a quoted speaker with a person's title) and never when it labels the
same name an organisation or place. The linking sieve below is the entity-resolution part and is unchanged.

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
A name is a person when the analyser labels any mention PERSON (and not mostly something else), or when it is a quoted
speaker with a person's title in front. Countries, teams, films and schemes are labelled otherwise, so they are never
shortened."""
from __future__ import annotations

import contextvars
import re
from dataclasses import dataclass, field

from . import spelling, titles

PARTICLES = {"al", "el", "bin", "bint", "ibn", "de", "van", "von"}
_TOKEN = re.compile(r"[A-Za-z][A-Za-z.'’-]*")
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
    from .people import BODY_END
    s = re.sub(r"\s+", " ", (raw or "").strip())
    if re.search(r"[’']s\s+\w+", s):                       # "Rahul's mother": a relation, not a name
        return Mention(raw, "", (), "relation", False)
    s = re.sub(r"\s*\([^)]*\)", "", s)                  # "(CERT-In)", "(other)"
    s = s.split(",")[0].strip()                          # "Varsha Singh, a senior civil official"
    toks = _TOKEN.findall(s)
    stop = _stoppers()
    roles = {w.lower() for w in titles.role_nouns()}
    run: list[str] = []
    for t in reversed(toks):
        b = _bare(t)
        low = b.lower()
        if b in stop or low in roles or (low.endswith("s") and low[:-1] in roles):
            break
        if b[:1].isupper() or (b.lower() in PARTICLES and run):
            run.append(re.sub(r"[’']s$", "", b))
        else:
            break
    run.reverse()
    while run and run[0].lower() in PARTICLES:
        run.pop(0)
    if len(run) >= 4 and len(run) % 2 == 0 and run[: len(run) // 2] == run[len(run) // 2:]:
        run = run[: len(run) // 2]                       # "Lokesh Adhikari Lokesh Adhikari"
    prefix = toks[: len(toks) - len(run)]
    pw = set(titles.person_title_words())
    titled = any(_bare(w) in pw or _bare(w).lower() in roles for w in prefix)
    title = " ".join(prefix)
    name_text = " ".join(run)
    acronym = len(run) >= 2 and any(len(t) >= 3 and t.isupper() for t in run)
    inst_prefix = prefix and prefix[-1].lower() in ("of", "for", "in") and any(_bare(w).lower() in BODY_END for w in prefix)
    if (len(run) >= 2 and run[-1].lower() in BODY_END) or acronym or inst_prefix:       # "Modi Sarkar", "BCCI Women": institutions
        return Mention(raw, title, tuple(run), "body", titled)
    if not run:
        return Mention(raw, title, (), "role", titled)
    return Mention(raw, title, tuple(run), "person" if titled else "name", titled)


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
        def loose(m: Mention) -> bool:       # "Chief Electoral Officer of Uttar Pradesh Navdeep Rinwa": the place leaked in
            return m.title.split()[-1:] in (["of"], ["for"], ["in"], ["from"])
        return max(self.mentions, key=lambda m: (not loose(m), written(m), len(m.tokens), sum(1 for x in self.mentions if x.keys == m.keys),
                                                 -len(m.raw)))

    @property
    def person(self) -> bool:
        return bool(self.why) and not self.vetoed

    vetoed: bool = False

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
        self.notperson: set[tuple] = set()      # names the analyser mostly labels an organisation or place
        self.links: list[tuple[tuple, tuple]] = []   # names a report itself calls one person (aliases.py)
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
            if source == "speaker":
                ev.add("speaker")
                if not m.titled:                      # a bare speaker string: ask the analyser what kind of name it is
                    from . import nlp
                    labels = {e.label for e in nlp.ents(f"{m.text} said on Monday.") if m.tokens[-1] in e.text}
                    if labels and labels <= nlp.NOT_PERSON_LABELS:
                        self.notperson.add(m.keys)
            if m.titled:
                ev.add("title")
        self._built = False
        return m

    def link(self, a: str, b: str) -> None:
        """Two names an outlet writes as one person (\"X alias Y\"): unified in build(), whatever else says."""
        ma, mb = parse(a), parse(b)
        if ma.tokens and mb.tokens and ma.keys != mb.keys:
            self.links.append((ma.keys, mb.keys))
            self._built = False

    def add_text(self, text: str) -> None:
        """Every named entity of a text. PERSON ones become mentions with "ner" evidence; the same name seen mostly as
        an organisation or place is recorded as not a person (a vote: one wrong label cannot make a person)."""
        from . import aliases, nlp
        for a, b in aliases.find(text):
            self.link(a, b)
        votes: dict[tuple, list[int]] = {}
        for e in nlp.ents(text):
            m = parse(e.text)
            if not m.tokens or m.kind in ("relation", "role"):
                continue
            v = votes.setdefault(m.keys, [0, 0])
            if e.label == nlp.PERSON:
                v[0] += 1
                self.add(e.text, "text", text)
            elif e.label in nlp.NOT_PERSON_LABELS:
                v[1] += 1
        for k, (yes, no) in votes.items():
            if yes > no:
                self.evidence.setdefault(k, set()).add("ner")
            elif no >= yes:
                self.notperson.add(k)

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
            # against the cluster's longest name only (the first member): "Singh Kapoor" and "Shatrujeet Kapoor" both fit
            # "Shatrujeet Singh Kapoor" and are one person with it, though they do not fit each other
            fit = [c for c in clusters if _fits(reps[k], reps[c[0]])]
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
        # 3. names a report itself says are one person are one person
        for ka, kb in self.links:
            ca = next((c for c in clusters if ka in c), None)
            cb = next((c for c in clusters if kb in c), None)
            if ca is not None and cb is not None and ca is not cb:
                ca.extend(cb)
                clusters.remove(cb)
        for c in clusters:
            self._make([m for k in c for m in groups[k]], False)
        for k, many in extra:
            self._make(groups[k], many)
        self._built = True
        return self

    def _make(self, members: list, ambiguous: bool) -> None:
        e = Entity(id=len(self.entities) + 1, ambiguous=ambiguous)
        for m, s in members:
            e.vetoed = e.vetoed or (m.keys in self.notperson and "title" not in self.evidence.get(m.keys, ()))
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


# ------------------------------------------------------------------ the story's table, shared by every module
_current: contextvars.ContextVar = contextvars.ContextVar("entity_table", default=None)


def for_items(items: list[dict]) -> EntityTable:
    """The table of one story: every statement's speaker (as a speaker) and every statement's text (analysed)."""
    t = EntityTable()
    for i in items:
        if i.get("speaker"):
            t.add(i["speaker"], "speaker", i.get("text") or "")
    t.add_text(" ".join(i.get("text") or "" for i in items))
    return t.build()


def use(table: EntityTable | None) -> None:
    """Make `table` the story every module (voice.speaker_key, style) is working on."""
    _current.set(table)


def current() -> EntityTable | None:
    return _current.get()


def person_key(raw: str | None) -> str | None:
    """The key of the person `raw` names in the current story, or None (not a person / no table / ambiguous surname)."""
    t = _current.get()
    if t is None or not raw:
        return None
    e = t.entity(raw)
    if e is not None and e.person and not e.ambiguous:
        return e.key
    return None
