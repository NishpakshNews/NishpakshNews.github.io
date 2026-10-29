"""House style applied by code to the finished article (owner, Oct 7 2026: "read like one author
writing for a reader, not like an AI"). The writer models do not follow style rules reliably, so code
does what can be done safely:

    surnames      a person is named in full once ("Air Marshal Ashutosh Dixit"), then by surname
                  ("Dixit"), as newspapers do; not when two people in the article share the surname
    said-chains   "Sarma said A. He said B. He added that C." -> "Sarma said A. B, he said. C, he added."
                  the attribution moves, it is never dropped

A name counts as a person only with evidence: a title or role before it in the article ("Chief
Minister", "Air Marshal", "jawan"), a speech verb after it ("X said"), or a statement's speaker.
Places and bodies ("Tel Aviv", "East Champaran", "Supreme Court") are never shortened.
"""
from __future__ import annotations

import re

# one registry for titles (config/titles.yaml, titles.py); no list of titles, places or bodies lives here any more
from . import titles as _titles  # noqa: E402
TITLES = set(_titles.person_title_words())      # not the bare qualifiers ("Law", "Health": "Law Commission" is no person)
PERSON_TITLES = set(TITLES)
KIN = {"wife", "husband", "son", "daughter", "father", "mother", "brother", "sister"}     # relationships, not titles
ROLES_LOWER = set(_titles.role_nouns()) | KIN
SPEECH = r"(?:said|says|told|added|stated|alleged|claimed|denied|announced|noted|asked|urged|wrote)"
NAME = r"[A-Z][a-z]+(?:-[A-Z]?[a-z]+)?|al-[A-Z][a-z]+"


def _candidates(text: str) -> set[str]:
    """The names of the persons the analyser finds in a text (spaCy PERSON entities, titles taken off, 2-4 words)."""
    from . import nlp
    out = set()
    for e in nlp.ents(text):
        if e.label != nlp.PERSON:
            continue
        name = _titles.strip(e.text).strip()
        if 2 <= len(name.split()) <= 4:
            out.add(name)
    return out


def people(text: str, speakers: list[str] | tuple = ()) -> dict[str, str]:
    """{full name: surname} for the persons in a text, shortenable without confusion: one identity per person
    (entities.py: NER votes, title and speech evidence, nesting of names), a body, event or government never a person."""
    from .entities import EntityTable
    t = EntityTable()
    for sp in speakers or ():
        if sp:
            t.add(sp, "speaker", text)
    t.add_text(text)
    return t.shortenable()


def intro_forms(names: dict[str, str], texts: list[str]) -> dict[str, str]:
    """{surname: the form that introduces the person}: the longest title phrase any statement or sentence writes
    right before one of the person's written forms (\"Assam Chief Minister Himanta Biswa Sarma\"), with the fullest
    written form of the name. One introduction per PERSON (the forms of one person share a surname), not per form."""
    out: dict[str, str] = {}
    by_short: dict[str, list[str]] = {}
    for full, short in names.items():
        by_short.setdefault(short, []).append(full)
    for short, forms in by_short.items():
        fullest = max(forms, key=lambda f: (len(f.split()), len(f)))
        best = ""
        for f in forms:
            for t in texts:
                tb = _titles.title_before(t, f)
                if len(tb) > len(best):
                    best = tb
        out[short] = f"{best} {fullest}" if best else fullest
    return out


def known_titles(names: dict[str, str], texts: list[str]) -> dict[str, set[str]]:
    """{surname: the title phrases the statements and sources really write before one of the person's forms}, lower case,
    spaces collapsed. A title the writer puts before the first mention is checked against it (Oct 29 2026: one sentence
    citing "Congress leader Rahul Gandhi" and "Leader of opposition in Lok Sabha Rahul Gandhi" was written with a blend of
    both, "Congress leader Lok Sabha Rahul Gandhi", which no report says)."""
    out: dict[str, set[str]] = {}
    for full, short in names.items():
        for t in texts:
            tb = _titles.title_before(t, full)
            if tb:
                out.setdefault(short, set()).add(" ".join(tb.lower().split()))
    return out


def title_is_reported(written: str, reported: set[str]) -> bool:
    """The title as written is one the reports write, or a piece of one (\"Finance Minister\" of \"Union Finance Minister\")."""
    w = " ".join(written.lower().split())
    return any(w == r or w in r for r in reported)


def mentions(t: str, names: dict[str, str]) -> list[tuple[int, int, str]]:
    """Every mention of a listed person in ONE text, found on the text as written: (start, end, surname), no two
    overlapping. Written forms come longest first; a bare surname is extended to the left over the person's own
    given names (\"Chandrababu Naidu\" when only \"N Chandrababu Naidu\" is a listed form), so a partial name is one
    mention, never a surname with a stray first name in front of it (Oct 26 2026: \"Chief Minister Chandrababu Andhra
    Pradesh Chief Minister N Chandrababu Naidu\")."""
    forms = sorted({(f, sh) for f, sh in names.items()} | {(sh, sh) for sh in names.values()},
                   key=lambda x: (-len(x[0].split()), -len(x[0])))
    own: dict[str, set[str]] = {}
    for f, sh in names.items():
        own.setdefault(sh, set()).update(f.split())
    taken: list[tuple[int, int, str]] = []
    for form, short in forms:
        for m in re.finditer(rf"(?<![\w-]){re.escape(form)}(?![\w-])", t):
            a, b = m.start(), m.end()
            if form == short:                                # a bare surname: take its own given names with it
                while True:
                    left = re.search(r"([A-Za-z][\w.'-]*)\s+$", t[:a])
                    if left and left.group(1) in own.get(short, ()) and left.group(1) != short:
                        a = left.start(1)
                    else:
                        break
            if any(a < y and x < b for x, y, _ in taken):
                continue
            taken.append((a, b, short))
    return sorted(taken)


def shorten_names(paragraphs: list[list[dict]], speakers: list[str] | tuple = (), sources: list[str] | tuple = ()) -> None:
    """A person is introduced once and then named by surname, whatever the writer wrote (owner, Oct 10 2026: names
    went wrong in both directions). By code, in reading order:
      * the first mention is the full introduction (title and full name); a bare surname or \"Title Surname\" that
        comes before the person has been introduced is expanded to it
      * every later mention is the surname alone: a full name or a title in front of the surname is dropped
    Only for persons code has evidence for (`people`): places and bodies are never touched.
    Mentions are found FIRST, on the text as written (`mentions`), and rewritten once; the introduction is kept per
    person, not per written form (a text patched form by form re-matched its own output: a doubled name, an
    introduction written twice)."""
    text = " ".join(s["text"] for p in paragraphs for s in p)
    # the statements know the full names the writer may have shortened away (\"Verma\" for \"Rajesh Verma\"); only the
    # persons the article names, in full or by surname, are kept
    names = {full: short for full, short in people(" ".join([text, *sources]), speakers).items()
             if re.search(rf"(?<![\w-]){re.escape(short)}(?![\w-])", text)}
    if not names:
        return
    intro = intro_forms(names, [text, *sources])
    reported = known_titles(names, list(sources))      # what the reports (not the writer) say; empty = nothing to check against
    if sources:                                        # the introduction's title comes from the reports, not from the writer's own text
        from_reports = intro_forms(names, list(sources))
        intro = {sh: (from_reports[sh] if reported.get(sh) else form) for sh, form in intro.items()}
    width: dict[str, int] = {}                    # words in the fullest written form of each person
    for full, short in names.items():
        width[short] = max(width.get(short, 0), len(full.split()))
    seen: set[str] = set()

    def shorten(t: str) -> str:
        out, last = [], 0
        for a, b, short in mentions(t, names):
            if a < last:
                continue
            written_name = t[a:b]
            # the title written in front of the name, taken WHOLE or not at all (owner, Oct 12 2026: a title of
            # the form \"Leader of Opposition\" lost only its end and read \"Lok Sabha Leader of Gandhi\")
            prefix = t[:a]
            at = _titles.title_start_in(t, a, extra=TITLES, extra_person=PERSON_TITLES)
            if at < len(prefix) and re.search(r"(?i)\bthe\s+$", prefix[:at]):
                at = re.search(r"(?i)\bthe\s+$", prefix[:at]).start()
            at = max(at, last)
            if at < len(prefix) and prefix[at] in "'\"\u2018\u201c":     # a quoted nickname ('Prime Minister Ambani') is the speaker's words: never shortened
                out.append(t[last:b])
                last = b
                seen.add(short)
                continue
            written = t[at:b]                            # the title as written, and the name
            if short in seen:
                new = short                              # every later mention, however written
            elif len(written_name.split()) >= width[short]:
                title_w = t[at:a].strip()
                if title_w and reported.get(short) and not title_is_reported(title_w, reported[short]):
                    new = intro[short]                   # a title no report writes (a blend of two): the introduction is the code's
                else:
                    new = written                        # the introduction stays as the writer wrote it
                seen.add(short)
            else:                                        # a surname before the person was introduced
                new = intro[short]
                seen.add(short)
            out += [t[last:at], new]
            last = b
        return "".join(out) + t[last:] if out else t

    for para in paragraphs:
        for sent in para:
            if sent.get("parts"):          # a sentence in coloured parts: each part, in order
                for k, part in enumerate(sent["parts"]):
                    t = shorten(part["text"])
                    part["text"] = t[:1].upper() + t[1:] if k == 0 else t
                sent["text"] = " ".join(p["text"].strip() for p in sent["parts"])
                continue
            t = shorten(sent["text"])
            sent["text"] = t[:1].upper() + t[1:]


from . import attribution


class Refs:
    """How the article refers to each person after the first mention (owner, Oct 8 2026): the surname,
    the role ("the MLA") when only one person has it, and "he" / "she" only with the outlets' evidence
    (voice.pronouns). Rotated, so a speaker's run does not read "Kabir said ... Kabir said ...". """

    def __init__(self, names: dict[str, str], pronouns: dict[str, str], roles: dict[str, str]):
        self.by_surname = {short: full for full, short in names.items()}
        self.pron, self.roles = pronouns, roles
        self.last_form: dict[str, str] = {}
        self.last_person: str | None = None

    def person(self, text: str) -> str | None:
        """The last person a text names (full name or surname)."""
        best, at = None, -1
        for short, full in self.by_surname.items():
            for m in re.finditer(rf"\b{re.escape(short)}\b", text):
                if m.start() > at:
                    best, at = full, m.start()
        return best

    def next(self, full: str, topic: bool = True) -> str:
        """The form for the next mention of a person, chosen by centering (Grosz, Joshi & Weinstein) and the
        incremental algorithm (Dale & Reiter), not rotated: a person who is still the topic (mentioned in the
        sentence before) is a pronoun when the outlets' evidence allows one; otherwise the role when it is theirs
        alone; otherwise the surname. The form just used for this person is not used twice in a row."""
        short = full.split()[-1]
        topic = topic or self.last_person == full           # the caller is continuing this person's run: still the topic
        ranked = ([self.pron[full]] if topic and full in self.pron else []) + \
                 ([self.roles[full]] if full in self.roles else []) + [short]
        prev = self.last_form.get(full)
        choice = next((o for o in ranked if o != prev), ranked[-1])
        self.last_form[full] = choice
        self.last_person = full
        return choice

    def allowed(self, full: str | None, pronoun: str) -> bool:
        return bool(full) and self.pron.get(full) == pronoun.lower()


def vary_attribution(paragraphs: list[list[dict]], refs: Refs | None = None, speakers_of=None) -> None:
    """In a run of sentences by one speaker, the second and later carry the attribution at the end
    ("..., he said." / "..., the MLA said." / "..., Kabir said."); "also stated" and "further stated" go.
    A "he" / "she" for someone the outlets do not call so becomes the surname (code never guesses a
    gender)."""
    from .voice import speaker_key
    refs = refs or Refs({}, {}, {})
    current = None

    def own(sent: dict, full: str | None) -> tuple[str | None, str | None]:
        """(the person to refer to, the name of a body) for this sentence: its statements' speaker, never the
        paragraph's last one (Oct 9 2026: Scindia's figures written as "..., Modi said", the Supreme Court's line
        as "..., she said", because "He" / "The ..." was read as whoever spoke before)."""
        sps = [x for x in (speakers_of(sent) if speakers_of else []) if x]
        if not sps:
            return full, None
        keys = {speaker_key(x) for x in sps}
        if full and speaker_key(full) in keys:
            return full, None
        person = next((refs.person(x) for x in sps if refs.person(x)), None)
        if person and speaker_key(person) in keys:
            return person, None
        return None, (sps[0] if len(keys) == 1 else None)

    def body_name(sp: str) -> str:
        return sp if sp.lower().startswith("the ") else f"the {sp}"

    from .voice import body_refs, is_body, wrong_speaker
    body_used: dict[str, int] = {}

    def body_run(sent: dict, prev: dict) -> str | None:
        """The run of one BODY's lines (owner, Oct 9 2026, story 16708: "The US Department of State said that ..."
        three times): the second and later end in "..., the department said." / "..., it said." / "..., they
        said." Only when the line before is the same body's (its statements' speaker, by key) and was attributed."""
        if not speakers_of or sent.get("parts"):
            return None
        sps = [x for x in speakers_of(sent) if x]
        keys = {speaker_key(x) for x in sps}
        prev_keys = {speaker_key(x) for x in speakers_of(prev) if x}
        if len(keys) != 1 or keys != prev_keys or refs.person(sps[0]) or not is_body(sps[0]):
            return None
        text = sent["text"].strip()
        options = body_refs(sps[0])
        sp = attribution.read(text)
        sp = sp if sp and sp.subject_first else None
        # a body opening with its own pronoun ("... claimed its primary activity ...") would read "Its ..., it claimed"
        if not sp or attribution.has_speech(sp.body) or wrong_speaker(text, sps, "", {}) \
                or re.match(r"(?i)(its|their|it|they)\b", sp.body):
            # "The US Department of State identified ..." after its own line: "The department identified ..."
            name = re.match(rf"^(?:The\s+)?{re.escape(re.sub(r'(?i)^the\s+', '', sps[0]))}\b", text)
            subj = next((o for o in options if o not in ("it", "they")), None)
            if name and subj and not attribution.has_speech(text[name.end():name.end() + 40]):
                return subj[:1].upper() + subj[1:] + text[name.end():]
            return None
        n = body_used.get(sps[0], 0)
        body_used[sps[0]] = n + 1
        ref = options[n % len(options)]
        return attribution.trailing(sp, ref, plain_added=True)

    for para in paragraphs:
        for k in range(len(para)):
            if para[k].get("parts"):
                continue                  # moving words across parts would break their colours
            cur = para[k]["text"].strip()
            named = refs.person(cur)
            if k > 0:
                varied = body_run(para[k], para[k - 1])
                if varied:
                    para[k]["text"] = varied
                    continue
            m = attribution.read(cur)
            m = m if m and m.subject_first else None
            if m and k > 0 and attribution.has_speech(para[k - 1]["text"]) and not attribution.has_speech(m.body):
                who = m.subject
                # "The ..." is the current speaker only when it is that speaker's own role ("The MLA"); "The Centre",
                # "The Supreme Court" are other speakers (Oct 9 2026, story 16197: "The Centre alleged ..." after
                # Kapil Sibal became "..., the advocate alleged", "The Supreme Court stated ..." after a line naming
                # Mishra became "..., she said")
                own_role = bool(current) and who.lower() == (refs.roles.get(current) or "").lower()
                pron = m.pronoun
                full = current if pron or own_role else (None if who.startswith("The ") else refs.person(who))
                if full and (pron or own_role) and speakers_of:
                    full, _ = own(para[k], full)
                if full and (pron or own_role or full in (current, refs.person(para[k - 1]["text"]))):
                    para[k]["text"] = attribution.trailing(m, refs.next(full))
                    current = full
                    continue
            opens = m and (k == 0 or not attribution.has_speech(para[k - 1]["text"]))
            if opens and (m.adverb or m.lemma == "add" or m.lemma in attribution.NEUTRAL_LEMMA):
                # "Kabir also stated / further stated / added that" with nothing before it to add to: "Kabir said"
                para[k]["text"] = attribution.without_adverb(cur, m, plain_added=True)
            # "he said" / "She added" for someone without the outlets' evidence: the surname
            t = para[k]["text"]
            for ps, pe, pw in reversed(attribution.pronoun_subjects(t)):
                full, body = own(para[k], refs.person(t[:ps]) or current)
                if body and is_body(body):
                    t = t[:ps] + body_name(body) + t[pe:]     # a body is never "he" / "she"
                elif body:
                    # a person the article's name list does not hold: the surname, never "the Raghoo Puri"
                    t = t[:ps] + body.split()[-1] + t[pe:]
                elif full and not refs.allowed(full, pw):
                    short = full.split()[-1]
                    t = t[:ps] + short + t[pe:]
            para[k]["text"] = t[:1].upper() + t[1:]
            current = refs.person(para[k]["text"]) or named or current


def polish(payload: dict) -> None:
    from .voice import pronouns, roles
    nar = payload.get("narrative") or {}
    paras = nar.get("paragraphs") or []
    if not paras:
        return
    items = []
    for k in ("undated", "established", "contested", "context"):
        items += payload.get(k) or []
    for tier in payload.get("timeline") or []:
        items += tier
    speakers = [i.get("speaker") or "" for i in items]
    text = " ".join(s["text"] for p in paras for s in p)
    names = people(text, speakers)
    refs = Refs(names, pronouns(items), roles(text, names))
    shorten_names(paras, speakers, [i.get("text") or "" for i in items])
    by_id = {i["id"]: i for i in items if "id" in i}
    speakers_of = lambda sent: [(by_id.get(i) or {}).get("speaker") for i in sent.get("ids") or []]   # noqa: E731
    vary_attribution(paras, refs, speakers_of)
    # a body of several people is "they", with a plural verb, never "it" (agreement.py, owner Oct 15 2026)
    from .agreement import fix_article as _plural_bodies
    nar["plural_bodies"] = _plural_bodies(paras)
    # last: whoever the reader has not been told about gets the context in brackets (owner, Oct 11 2026)
    from .gloss import gloss
    gloss(paras, speakers_of, [i.get("text") or "" for i in items], names)
    # and what a thing is, the first time it is written without the reader having been told (refs.py, Oct 15 2026)
    from .refs import gloss_article
    refs_of = lambda sent: [r for i in sent.get("ids") or [] for r in (by_id.get(i) or {}).get("refs") or []]   # noqa: E731
    nar["refs"] = gloss_article(paras, payload.get("headline") or "", refs_of)
    # one date form in what we write, "15 October" (when.py, Oct 16 2026: the audit found both forms in 57% of
    # mixed-language articles); outlets' statements are not touched
    from .when import house_dates
    for para in paras:
        for sent in para:
            if sent.get("parts"):
                for part in sent["parts"]:
                    part["text"] = house_dates(part["text"])
                sent["text"] = " ".join(p["text"].strip() for p in sent["parts"])
            else:
                sent["text"] = house_dates(sent["text"])
    if payload.get("headline"):
        payload["headline"] = house_dates(payload["headline"])
