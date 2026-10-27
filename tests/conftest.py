import dataclasses

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "settle: keep the wait for coverage to settle (editions.py)")
    config.addinivalue_line("markers", "carry: keep the carry-over of unused hourly allowances (carry.py)")


@pytest.fixture(autouse=True)
def two_databases(monkeypatch, tmp_path):
    """Production keeps reader tables and run logs in Supabase and the newsroom in the job's own Postgres
    (db.READER_TABLES, Oct 10 2026): every test runs the same way, each with its own readers' database, so a
    statement sent to the wrong database, or mixing the two, fails here."""
    monkeypatch.setenv("READERS_DATABASE_URL", f"sqlite:///{tmp_path / 'readers.db'}")


@pytest.fixture(autouse=True)
def model_verdicts_on(monkeypatch):
    """Red verdicts are on hold in production (SETTINGS.model_verdicts = False); the tests keep the
    machinery working for when a second model family is available."""
    import nishpaksh.run as run_mod
    monkeypatch.setattr(run_mod, "SETTINGS", dataclasses.replace(run_mod.SETTINGS, model_verdicts=True))


@pytest.fixture(autouse=True)
def no_settle_wait(monkeypatch, request):
    """Articles are written once coverage has settled (3 quiet hours). Tests run on articles fetched
    seconds ago, so the wait is off unless a test is about it (marked `settle`). No archive reads."""
    monkeypatch.setenv("NISHPAKSH_ARCHIVE_URL", "")
    if request.node.get_closest_marker("settle"):
        return
    import nishpaksh.editions as ed
    monkeypatch.setattr(ed, "SETTINGS", dataclasses.replace(ed.SETTINGS, settle_quiet_hours=0, read_wait_hours=0))


@pytest.fixture(autouse=True)
def pipeline_then_desk(monkeypatch):
    """In production the writing desk is its own job (desk.py); in tests a pipeline run is followed by
    the desk, so a run ends with what a reader would see."""
    import functools
    import nishpaksh.run as run_mod
    monkeypatch.setattr(run_mod, "run", functools.partial(run_mod.run, then_write=True))


@pytest.fixture(autouse=True)
def carry_over_off(monkeypatch, request):
    """Unused hourly allowances carry to later hours (carry.py, Oct 11 2026). Older tests are about one hour at a
    time, so carry-over is off unless a test is about it (marked `carry`)."""
    if request.node.get_closest_marker("carry"):
        return
    import nishpaksh.config as cfg
    monkeypatch.setattr(cfg, "SETTINGS", dataclasses.replace(cfg.SETTINGS, carry_over=False))


def fake_nli(pairs):
    """Stand-in for the local NLI model (nli.py): wording decides. A reads as entailing B when B's words are all in A
    (or the two share half their words with the same figures); the same wording with other figures or a negation
    flipped contradicts."""
    import re
    from nishpaksh import checkworthy
    out = []
    for a, b in pairs:
        if b in (checkworthy.FACT, checkworthy.OPINION):       # check-worthiness: opinion words mark a characterisation
            op = bool(re.search(r"conspiracy|negligen|blame", a, re.I))
            out.append((0.9, 0.05, 0.05) if (b == checkworthy.FACT) != op else (0.05, 0.9, 0.05))
            continue
        from nishpaksh import events
        if b in (events.DEATH, events.DECISIVE, events.ROUTINE):   # decisive acts: scripted by a few words
            hit = {events.DEATH: r"\b(died|dead|killed|deaths?)\b",
                   events.DECISIVE: r"\b(arrest\w*|ordered|inaugurat\w*|announced|signed|resign\w*)\b",
                   events.ROUTINE: r"\b(met|heard|said that nothing)\b"}[b]
            out.append((0.9, 0.05, 0.05) if re.search(hit, a, re.I) else (0.1, 0.8, 0.1))
            continue
        scripted = _risk_script().get(b)                   # a concern definition of express.yaml (risk.py): scripted by words
        if scripted is not None:
            out.append((0.9, 0.05, 0.05) if scripted.search(a) else (0.05, 0.9, 0.05))
            continue
        if "passed lab tests" in a and "substandard" in b:      # the scripted court filing contradicts the claim
            out.append((0.03, 0.07, 0.90))
            continue
        wa = {w for w in re.findall(r"[a-z]+", a.lower()) if len(w) > 2}
        wb = {w for w in re.findall(r"[a-z]+", b.lower()) if len(w) > 2}
        na, nb = set(re.findall(r"\d[\d,.]*", a)), set(re.findall(r"\d[\d,.]*", b))
        jac = len(wa & wb) / max(1, len(wa | wb))
        neg = ("not" in wa) != ("not" in wb)
        if jac >= 0.5 and (na != nb or neg):
            out.append((0.03, 0.07, 0.90))
        elif jac >= 0.5 and na == nb:
            out.append((0.95, 0.03, 0.02))
        elif wb and wb <= wa and nb <= na and not neg:
            out.append((0.92, 0.06, 0.02))
        else:
            out.append((0.08, 0.87, 0.05))
    return out


_RISK_WORDS = {
    "harm:crime": r"\b(arrest\w*|detained|custody|bail|jail\w*|FIR|chargesheet|charge sheet|lawsuit|sued|sues|raids?|probe|murder\w*)\b"
                  r"|(?<!\bon )(?<!\bCentre )(?<!\btennis )(?<!\bbadminton )(?<!\bbasketball )\b(court|tribunal|verdict|judge)\b",
    "harm:death": r"\b(died|dies|dead|killed|kills|deaths?|suicide|crash\w*|accident|injured)\b|मौत|हादसा|दुर्घटना",
    "harm:accusation": r"\b(accused|accuses|alleg\w*|fraud|scam|scandal|cheating|abuse|harassment|rape|assault|molest)\b",
    "harm:ban": r"\b(banned|suspended|doping|dope|match-fixing)\b",
    "harm:unrest": r"\b(riot|violence|terror|hate|communal|boycott)\b",
    "government:acts": r"\b(RBI|SEBI|ministry|regulator|government|Centre|minister)\b",
    "government:policy": r"\b(scheme|tariff|tax|GST|law|policy)\b",
    "market:prices": r"\b(shares?|Sensex|Nifty|stocks?|gold|crude|rally|surge[sd]?)\b",
    "market:economy": r"\b(inflation|GDP|repo|interest rates?)\b",
    "market:advice": r"\b(stocks to buy|buy or sell|target price)\b",
    "speculation:rumour": r"\b(reportedly|leak\w*|rumou?rs?|sources)\b",
    "speculation:forecast": r"\b(likely|could|prediction|in talks|expected to)\b|(?-i:\bmay\b|\b[A-Z][a-z]+ May (?=[a-z]))",
    "gossip:private_life": r"\b(dating|spotted|wedding|breakup|boyfriend|girlfriend)\b",
    "gossip:box_office": r"\b(box office|opening day|crore on)\b",
    "service:list": r"\b(top \d+|\d+ best|best \w+( \w+)? under|top 5)\b",
    "service:live": r"\b(live score|live updates|live blog|rate today|horoscope|price today)\b",
    "service:view": r"\b(opinion|editorial|explainer|sponsored)\b",
}


def _risk_script():
    """{definition sentence: compiled words} for the concerns of config/express.yaml: stands in for the model's judgement of
    each definition. "May" the month does not fire the forecast definition (a real model reads the sentence, not the word)."""
    import re
    from nishpaksh import express
    out = {}
    for c, keys in (express.cfg().get("concerns") or {}).items():
        for k, sentence in keys.items():
            pat = _RISK_WORDS.get(f"{c}:{k}")
            if pat:
                out[sentence] = re.compile(pat, re.IGNORECASE)
    return out


@pytest.fixture(autouse=True)
def local_nli(monkeypatch):
    """The NLI model is not downloaded in tests."""
    from nishpaksh import nli
    nli.set_backend(fake_nli)
    yield
    nli.set_backend(None)


def fake_ner(text):
    """Stand-in for spaCy (nlp.py): a run of 2-4 capitalised words is a PERSON, unless its last word names an institution
    (then ORG). Good enough to exercise the callers; the real model is checked in the audit."""
    import re
    from nishpaksh import nlp
    from nishpaksh.people import BODY_END
    out = []
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    for m in re.finditer(r"(?<![\w-])((?:[A-Z][a-z]+)(?:\s+[A-Z][a-z]+){1,5})(?![\w-])", text):
        words = m.group(1).split()
        while words and words[0].lower() in ENGLISH_STOP_WORDS:         # "While Humayun Kabir": not part of the name
            words = words[1:]
        if len(words) < 2:
            continue
        places = {"champaran", "tel", "aviv", "saudi", "arabia", "new", "zealand", "uttar", "pradesh", "delhi", "kolkata",
                  "palatine", "street", "games", "league", "asian", "super", "agreement"}   # a gazetteer, for the fake only
        label = "ORG" if words[-1].lower() in BODY_END | {"team", "survey", "exercise", "women"} else "GPE" if {w.lower() for w in words} & places else "PERSON"
        out.append(nlp.Ent(" ".join(words), label, m.start(1), m.end(1)))
    return out


def fake_chunker(text):
    """Stand-in for spaCy noun chunks: a determiner, up to three lower-case words, the last one is the head."""
    import re
    return [(m.start(), m.end(), m.group(0), m.group(0).split()[-1].lower().rstrip("s"),
             "NNS" if m.group(0).endswith("s") else "NN", "")
            for m in re.finditer(r"(?<![\w'’-])(?:[Tt]he|[Tt]his|[Tt]hat|[Tt]hese|[Tt]hose|[Ss]aid|[Ss]uch)(?:\s+(?!(?:is|was|are|were|has|have|had|said|says|will|would|could|may|might|that|and|of|in|on|at|to|for|by|with)\b)(?![a-z-]+ed\b)[a-z][a-z-]*){1,2}", text)]


_PLURAL_HEADS = {"was": ("be", "VBD"), "is": ("be", "VBZ"), "has": ("have", "VBZ"), "says": ("say", "VBZ"),
                 "said": ("say", "VBD"), "were": ("be", "VBD"), "are": ("be", "VBP"), "have": ("have", "VBP"),
                 "planning": ("plan", "VBG"), "examining": ("examine", "VBG"), "considering": ("consider", "VBG"),
                 "reviewing": ("review", "VBG"), "believes": ("believe", "VBZ"), "checking": ("check", "VBG"),
                 "fled": ("flee", "VBD")}


def fake_parser(text):
    """Stand-in for the dependency parse: every word is a token; \"it\" is the subject of the next verb word, the object
    after a preposition or an object verb, and an expletive before is / was + an adjective of the usual kind."""
    import re
    from nishpaksh import nlp
    toks = [m for m in re.finditer(r"[A-Za-z’']+", text)]
    out = []
    for i, m in enumerate(toks):
        w = m.group(0)
        lemma, tag = _PLURAL_HEADS.get(w.lower(), (w.lower(), "NN"))
        out.append([i, w, m.start(), m.end(), lemma, tag, "", "dep", i])
    for i, t in enumerate(out):
        if t[1].lower() in ("it", "its", "itself"):
            nxt = next((j for j in range(i + 1, len(out)) if out[j][5] != "NN"), None)
            prev = out[i - 1][1].lower() if i else ""
            k = i + 3 if i + 2 < len(out) and out[i + 2][1].lower() == "not" else i + 2
            expl = k < len(out) and out[i + 1][1].lower() in ("is", "was") and out[k][1].lower() in (
                "clear", "unclear", "likely", "raining", "known", "possible")
            if expl:
                t[7] = "expl"
            elif prev in ("asked", "told", "urged", "to", "from", "with", "against", "of", "by", "for", "on", "at", "in", "before"):
                t[7] = "pobj"
            elif nxt is not None:
                t[7], t[8] = "nsubj", nxt
    _speech_structure(text, toks, out)
    return [nlp.Tok(*t[:7], t[7], t[8]) for t in out]


_SPEECH_FORMS = {"said": "say", "says": "say", "stated": "state", "states": "state", "added": "add", "adds": "add",
                 "noted": "note", "claimed": "claim", "alleged": "allege", "announced": "announce",
                 "mentioned": "mention", "remarked": "remark", "asserted": "assert", "maintained": "maintain",
                 "denied": "deny", "warned": "warn", "insisted": "insist", "explained": "explain"}
_ATTRIB_ADVERBS = ("also", "further", "then", "later", "additionally")
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _speech_structure(text, toks, out):
    """The parse of an attribution for the stand-in: the first speech verb is the root; the words before it are its
    subject (after the last comma when the sentence opens with the reported clause); an adverb, an "on <day>" phrase
    and a "that" hang on the verb; the reported clause is the rest, headed by its first word."""
    v = next((i for i, t in enumerate(out) if i > 0 and t[1].lower() in _SPEECH_FORMS), None)
    if v is None:
        return
    start = toks[v].start()
    comma = text.rfind(",", 0, start)
    body_first = comma != -1 and text[comma + 1:start].strip() != "" and v > 0
    lo = next((i for i, t in enumerate(out) if t[2] > comma), v) if body_first else 0
    subj = [i for i in range(lo, v) if out[i][1].lower() not in _ATTRIB_ADVERBS]
    advs = [i for i in range(lo, v) if out[i][1].lower() in _ATTRIB_ADVERBS]
    if not subj:
        return
    out[v][4], out[v][5], out[v][6], out[v][7], out[v][8] = _SPEECH_FORMS[out[v][1].lower()], "VBD", "VERB", "ROOT", v
    for j in range(v + 1, len(out)):                       # a later "he said" / "she added" inside the reported part
        if out[j][1].lower() in _SPEECH_FORMS and out[j - 1][1].lower() in ("he", "she"):
            out[j][4], out[j][5], out[j][6] = _SPEECH_FORMS[out[j][1].lower()], "VBD", "VERB"
            out[j - 1][7], out[j - 1][8] = "nsubj", j
    for i in subj:
        out[i][7], out[i][8] = ("nsubj", v) if i == subj[-1] else ("compound", subj[-1])
    for i in advs:
        out[i][7], out[i][8] = "advmod", v
    rest = list(range(v + 1, len(out))) if not body_first else list(range(0, lo))
    j = 0
    if not body_first:
        if rest and out[rest[0]][1].lower() == "on" and len(rest) > 1 and out[rest[1]][1].lower() in _DAYS:
            out[rest[0]][7], out[rest[0]][8] = "prep", v
            out[rest[1]][7], out[rest[1]][8] = "pobj", rest[0]
            j = 2
    else:
        tail = [i for i in range(v + 1, len(out))]
        if tail and out[tail[0]][1].lower() == "on" and len(tail) > 1 and out[tail[1]][1].lower() in _DAYS:
            out[tail[0]][7], out[tail[0]][8] = "prep", v
            out[tail[1]][7], out[tail[1]][8] = "pobj", tail[0]
    body = rest[j:]
    if not body:
        return
    mark = None
    if out[body[0]][1].lower() == "that" and len(body) > 1:
        mark, body = body[0], body[1:]
    head = next((out[i][8] for i in body if out[i][7] == "nsubj" and out[i][8] in body), None)
    if head is None:
        head = body[0]
    out[head][7], out[head][8] = "ccomp", v
    if mark is not None:
        out[mark][7], out[mark][8] = "mark", head
    for i in body:
        if i != head and out[i][7] == "dep":
            out[i][8] = head


@pytest.fixture(autouse=True)
def local_ner(monkeypatch):
    from nishpaksh import nlp
    from nishpaksh import langcheck
    langcheck.set_backend(lambda text: [])
    nlp.set_chunker(fake_chunker)
    nlp.set_parser(fake_parser)
    from nishpaksh import nlp
    nlp.set_backend(fake_ner)
    yield
    nlp.set_backend(None)
    nlp.set_chunker(None)
    nlp.set_parser(None)
    langcheck.set_backend(None)
