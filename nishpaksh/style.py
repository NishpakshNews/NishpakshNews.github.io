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
    """{full name: the form that introduces the person}: the longest title phrase any statement or sentence
    writes right before the name (\"Assam Chief Minister Himanta Biswa Sarma\"), or the full name alone."""
    out = {}
    for full in names:
        best = ""
        for t in texts:
            tb = _titles.title_before(t, full)
            if len(tb) > len(best):
                best = tb
        out[full] = f"{best} {full}" if best else full
    return out


def shorten_names(paragraphs: list[list[dict]], speakers: list[str] | tuple = (), sources: list[str] | tuple = ()) -> None:
    """A person is introduced once and then named by surname, whatever the writer wrote (owner, Oct 10 2026: names
    went wrong in both directions). By code, in reading order:
      * the first mention is the full introduction (title and full name); a bare surname or \"Title Surname\" that
        comes before the person has been introduced is expanded to it
      * every later mention is the surname alone: a full name or a title in front of the surname is dropped
    Only for persons code has evidence for (`people`): places and bodies are never touched."""
    text = " ".join(s["text"] for p in paragraphs for s in p)
    # the statements know the full names the writer may have shortened away (\"Verma\" for \"Rajesh Verma\"); only the
    # persons the article names, in full or by surname, are kept
    names = {full: short for full, short in people(" ".join([text, *sources]), speakers).items()
             if re.search(rf"(?<![\w-]){re.escape(short)}(?![\w-])", text)}
    if not names:
        return
    intro = intro_forms(names, [text, *sources])
    seen: set[str] = set()
    pats = {full: re.compile(rf"(?<![\w-])(?:(?P<full>{re.escape(full)})|(?P<sur>{re.escape(short)}))(?![\w-])")
            for full, short in names.items()}

    def shorten(t: str) -> str:
        for full, short in names.items():
            out, last = [], 0
            for m in pats[full].finditer(t):
                if m.start() < last:
                    continue
                # the title written in front of the name, taken WHOLE or not at all (owner, Oct 12 2026: a title of
                # the form \"Leader of Opposition\" lost only its end and read \"Lok Sabha Leader of Gandhi\")
                prefix = t[:m.start()]
                at = _titles.title_start(prefix, extra=TITLES, extra_person=PERSON_TITLES)
                if at < len(prefix) and re.search(r"(?i)\bthe\s+$", prefix[:at]):
                    at = re.search(r"(?i)\bthe\s+$", prefix[:at]).start()
                at = max(at, last)
                if at < len(prefix) and prefix[at] in "'\"\u2018\u201c":     # a quoted nickname ('Prime Minister Ambani') is the speaker's words: never shortened
                    out += [t[last:m.end()]]
                    last = m.end()
                    seen.add(full)
                    continue
                written = t[at:m.end()]                  # the title as written, and the name
                if m.group("full"):
                    if full not in seen:               # the introduction stays as the writer wrote it
                        seen.add(full)
                        new = written
                    else:
                        new = short
                elif full not in seen:                 # a surname before the person was introduced
                    seen.add(full)
                    new = intro[full]
                else:
                    new = short                        # \"Chief Minister Sarma\" after the introduction
                out += [t[last:at], new]
                last = m.end()
            t = "".join(out) + t[last:] if out else t
        return t

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


CHAIN = re.compile(r"^(?P<who>He|She|They|The [a-z]+(?: [a-z]+)?|(?:[A-Z][\w.-]+\s+){0,3}[A-Z][\w.-]+)\s+"
                   r"(?:(?P<adv>also|further|then|later|additionally)\s+)?"
                   r"(?P<verb>said|added|stated|noted|claimed|alleged|maintained|mentioned|remarked|asserted)"
                   r"(?P<day>\s+on\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday))?(?:\s+that)?,?\s+"
                   r"(?P<body>[^\"“”]{20,}?)(?P<end>[.!?])$")
ATTRIB = re.compile(rf"\b{SPEECH}\b")
PRON_ATTRIB = re.compile(r"(?:^|(?<=, ))(He|She|he|she)(?=\s+(?:also\s+|further\s+)?(?:said|added|stated|noted|claimed|alleged|told|maintained)\b)")
NEUTRAL = {"stated": "said", "mentioned": "said", "remarked": "said", "asserted": "said", "noted": "said"}
BODY_LEAD = re.compile(r"^(?P<who>(?:The\s+)?[A-Z][^,\"“”]{1,70}?)\s+(?:(?:also|further|additionally)\s+)?"
                       r"(?P<verb>said|stated|added|noted|announced|alleged|claimed|maintained|asserted)(?:\s+that)?,?\s+"
                       r"(?P<body>[^\"“”]{20,}?)(?P<end>[.!?])$")


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
        m = BODY_LEAD.match(text)
        # a body opening with its own pronoun ("... claimed its primary activity ...") would read "Its ..., it claimed"
        if not m or ATTRIB.search(m.group("body")) or wrong_speaker(text, sps, "", {}) \
                or re.match(r"(?i)(its|their|it|they)\b", m.group("body")):
            # "The US Department of State identified ..." after its own line: "The department identified ..."
            name = re.match(rf"^(?:The\s+)?{re.escape(re.sub(r'(?i)^the\s+', '', sps[0]))}\b", text)
            subj = next((o for o in options if o not in ("it", "they")), None)
            if name and subj and not ATTRIB.search(text[name.end():name.end() + 40]):
                return subj[:1].upper() + subj[1:] + text[name.end():]
            return None
        n = body_used.get(sps[0], 0)
        body_used[sps[0]] = n + 1
        ref = options[n % len(options)]
        verb = "said" if m.group("verb") == "added" else NEUTRAL.get(m.group("verb"), m.group("verb"))
        body = m.group("body").rstrip(",;: ")
        return f"{body[:1].upper()}{body[1:]}, {ref} {verb}{m.group('end')}"

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
            m = CHAIN.match(cur)
            if m and k > 0 and ATTRIB.search(para[k - 1]["text"]) and not ATTRIB.search(m.group("body")):
                who = m.group("who")
                # "The ..." is the current speaker only when it is that speaker's own role ("The MLA"); "The Centre",
                # "The Supreme Court" are other speakers (Oct 9 2026, story 16197: "The Centre alleged ..." after
                # Kapil Sibal became "..., the advocate alleged", "The Supreme Court stated ..." after a line naming
                # Mishra became "..., she said")
                own_role = bool(current) and who.lower() == (refs.roles.get(current) or "").lower()
                pron = who in ("He", "She", "They")
                full = current if pron or own_role else (None if who.startswith("The ") else refs.person(who))
                if full and (pron or own_role) and speakers_of:
                    full, _ = own(para[k], full)
                if full and (pron or own_role or full in (current, refs.person(para[k - 1]["text"]))):
                    ref = refs.next(full)
                    verb = NEUTRAL.get(m.group("verb"), m.group("verb"))
                    body = m.group("body").rstrip(",;: ")
                    para[k]["text"] = f"{body[:1].upper()}{body[1:]}, {ref} {verb}{m.group('day') or ''}{m.group('end')}"
                    current = full
                    continue
            opens = m and (k == 0 or not ATTRIB.search(para[k - 1]["text"]))
            if opens and (m.group("adv") or m.group("verb") == "added" or m.group("verb") in NEUTRAL):
                # "Kabir also stated / further stated / added that" with nothing before it to add to: "Kabir said"
                verb = "said" if m.group("verb") == "added" else NEUTRAL.get(m.group("verb"), m.group("verb"))
                adv = rf"{m.group('adv')}\s+" if m.group("adv") else ""
                para[k]["text"] = re.sub(rf"^({re.escape(m.group('who'))})\s+{adv}{m.group('verb')}\b",
                                         rf"\1 {verb}", cur, count=1)
            # "he said" / "She added" for someone without the outlets' evidence: the surname
            t = para[k]["text"]
            for pm in reversed(list(PRON_ATTRIB.finditer(t))):
                full, body = own(para[k], refs.person(t[:pm.start()]) or current)
                if body and is_body(body):
                    t = t[:pm.start()] + body_name(body) + t[pm.end():]     # a body is never "he" / "she"
                elif body:
                    # a person the article's name list does not hold: the surname, never "the Raghoo Puri"
                    t = t[:pm.start()] + body.split()[-1] + t[pm.end():]
                elif full and not refs.allowed(full, pm.group(1)):
                    short = full.split()[-1]
                    t = t[:pm.start()] + short + t[pm.end():]
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
