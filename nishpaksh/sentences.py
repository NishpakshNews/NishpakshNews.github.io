"""Grammar of the sentence and of the join between sentences (owner, Oct 10 2026, phase 4 of "grammar, not rules").

Phase 3 fixed WHICH statements share a paragraph and how a paragraph opens. What was left is inside the paragraph:
one claim per sentence, a repeated subject, and how a sentence connects to the one before it. (Oct 16 2026, owner:
PARALLEL statements, one actor doing one thing to several things, are joined into one sentence: parallel_groups.) Same direction as
before: the writer is GIVEN the connection, code APPLIES the safe fixes, and nothing is a new prohibition that
drops a sentence. No model in this module.

  link_line   GIVEN to the writer with each statement after the first of its paragraph: how its sentence connects
              to the statement before it (same speaker, an answer, a contrast, a later time, the same subject
              to be referred back to). Nothing for a statement that simply starts a new point.
  strip_filler  APPLIED: "Furthermore, ..." / "Notably, ..." / "Importantly, ..." carry no fact (and "notably" /
              "importantly" add an emphasis no statement has): the word is taken off.
  split_stacked APPLIED: one sentence of "A; B" that cites several statements and is long is two sentences, one
              claim each, when every statement belongs clearly to one half. A contradiction, a response or an
              updated figure is never split from its partner.
  polish      runs both over the finished paragraphs. Every changed sentence is checked again by EVERY check of
              narrative.py (the `check` it is given) and kept only if it passes; otherwise the sentence stays as
              it was. So the worst case is the sentence the writer wrote, never a weaker one.
  stats       what code can still see afterwards, counted not enforced: two sentences in a row opening alike,
              a sentence past LONG words, a sentence with no link to the one before. Read with tools/replay.py
              (`narrative.flow`): a high count says the prompt's LINK lines are still not holding.
"""
from __future__ import annotations

import datetime as dt
import re

from . import grammar, voice

LONG = 45               # words: a sentence past this is counted as run-on
STACKED_WORDS = 30      # a sentence of two clauses citing 2+ statements is split past this many words (or at 3+ ids)
MIN_HALF = 4            # words in each half of a split

# no fact in these: they only announce that another sentence follows; "However" / "Meanwhile" / "Then" are NOT here
# (they say contrast or time)
FILLER = re.compile(r"(?i)^(?:furthermore|moreover|additionally|in addition|notably|importantly|interestingly|"
                    r"what is more|it is worth noting that|it should be noted that)\s*,\s*")
FILLER_THAT = re.compile(r"(?i)^(?:it is worth noting that|it should be noted that)\s+")

# an opening that links a sentence to the one before by time or by contrast
LINKING_OPEN = re.compile(r"(?i)^(?:then|later|earlier|after|before|since|until|meanwhile|however|but|and|also|"
                          r"on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d)|"
                          r"in (?:response|contrast|january|february|march|april|may|june|july|august|september|"
                          r"october|november|december|\d)|the (?:next|following|previous) )\b")


# ------------------------------------------------------------------ helpers (narrative / plan are imported late: they import us)
def _words(text: str) -> set[str]:
    from . import narrative
    return narrative._subject_words(text)


def _speaker(i: dict) -> str | None:
    return voice.speaker_key(i.get("speaker")) if i.get("speaker") else None


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _when(i: dict) -> str:
    from . import narrative
    return narrative.english_when(i.get("time") or {})


# ------------------------------------------------------------------ parallel statements (owner, Oct 16 2026)
# "Modi will inaugurate a petroglyph park." "Modi will inaugurate 40 water bodies." ... five sentences in a row read
# like a list cut into lines. The owner: "they should be joined". Statements of ONE paragraph with the same actor,
# the same action, the same stance and the same time, each about a different thing, are PARALLEL: the writer is
# told to write them as one sentence that names the actor and the verb once and lists the things. Each keeps its own
# colour: when their statuses differ the sentence is written in parts, one per statement (narrative._with_parts
# allows MAX_PARALLEL parts for one parallel group). Speech ("said", "alleged") is not here: one speaker's points
# are already carried by one "said" (the same-speaker LINK).
MAX_PARALLEL = 6
SPEECH_ACTIONS = {"say", "claim", "alleg", "deni", "deny", "state", "tell", "told", "add", "note", "accus", "assert",
                  "repli", "respond", "argu", "stress", "emphasis", "urg", "warn", "ask", "call"}


def _who(i: dict) -> tuple[frozenset, str]:
    who = str((i.get("frame") or {}).get("who") or "").strip()
    from . import titles
    skip = {w.lower() for w in titles.title_words()} | {"the", "a", "an"}
    names = frozenset(w.lower() for w in re.findall(r"\b[A-Z][\w'-]+", who) if w.lower() not in skip)
    return names, re.sub(r"\W+", " ", who.lower()).strip()


def _same_who(a: dict, b: dict) -> bool:
    (na, wa), (nb, wb) = _who(a), _who(b)
    if not wa or not wb:
        return False
    return bool(na & nb) if na and nb else wa == wb


def _parallel_key(i: dict) -> tuple | None:
    from .frames import action_key, words
    f = i.get("frame") or {}
    act = action_key(f.get("action"))
    if not act or not f.get("who") or not str(f.get("what") or "").strip():
        return None
    if set(act.split()) & SPEECH_ACTIONS:
        return None
    if i.get("verdict") in ("disputed", "false") or i.get("update_of") or i.get("updated_by") or i.get("adds_to"):
        return None
    return (act, _speaker(i) or "", bool(f.get("negated")), _when(i))


def bundle_sets(items: list[dict]) -> list[list[int]]:
    """Groups of statements that are pieces of one report sentence (bundles.py): statements sharing a `bundle_roots` entry,
    directly or through a chain of shared facts, in the order given. A group of 2 to MAX_PARALLEL; a bigger chain is left
    as separate statements (too much for one sentence)."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    owner: dict[str, int] = {}
    for i in items:
        if not i.get("bundle_roots"):
            continue
        parent.setdefault(i["id"], i["id"])
        for r in i["bundle_roots"]:
            if r in owner:
                parent[find(i["id"])] = find(owner[r])
            else:
                owner[r] = i["id"]
    groups: dict[int, list[int]] = {}
    for i in items:
        if i["id"] in parent:
            groups.setdefault(find(i["id"]), []).append(i["id"])
    return [g for g in groups.values() if 2 <= len(g) <= MAX_PARALLEL]


def bundle_groups(plan_: list, by_id: dict) -> dict[int, list[int]]:
    """{statement id: the ids of its bundle, in plan order} for the pieces of one report sentence that stand in ONE paragraph."""
    out: dict[int, list[int]] = {}
    for p in plan_:
        for g in bundle_sets([by_id[x] for x in p.ids if x in by_id]):
            for x in g:
                out[x] = g
    return out


def parallel_groups(plan_: list, by_id: dict) -> dict[int, list[int]]:
    """{statement id: the ids of its parallel group, in plan order} for the statements of each paragraph that share
    actor, action, speaker, negation and time and differ in what they are about (groups of 2 to MAX_PARALLEL)."""
    from . import plan
    from .frames import words
    out: dict[int, list[int]] = {}
    for p in plan_:
        groups: list[list[dict]] = []
        for x in p.ids:
            i = by_id.get(x)
            k = _parallel_key(i) if i else None
            if k is None:
                continue
            for g in groups:
                h = g[0]
                if (_parallel_key(h) == k and _same_who(h, i) and len(g) < MAX_PARALLEL
                        and not any(plan._links(m) & {i["id"]} or plan._links(i) & {m["id"]} for m in g)
                        and all(words((m.get("frame") or {}).get("what")) != words((i.get("frame") or {}).get("what"))
                                for m in g)):
                    g.append(i)
                    break
            else:
                groups.append([i])
        for g in groups:
            if len(g) >= 2:
                ids = [m["id"] for m in g]
                for m in ids:
                    out[m] = ids
    return out


def keep_together(plan_: list, groups: dict[int, list[int]]) -> None:
    """Each paragraph's parallel statements one after another, at the place of the group's first (in place)."""
    for p in plan_:
        new, done = [], set()
        for x in p.ids:
            if x in done:
                continue
            g = [m for m in groups.get(x, [x]) if m in p.ids] or [x]
            new += [m for m in g if m not in done]
            done |= set(g)
        p.ids = new


# ------------------------------------------------------------------ given to the writer
def link_line(item: dict, prev: dict | None) -> str | None:
    """How `item`'s sentence connects to the statement before it in the paragraph, or None when it starts a new
    point (the writer then needs no connective). The first rule that applies is the one given."""
    if prev is None:
        return None
    p = prev["id"]
    if prev["id"] in (item.get("conflicts_with") or []) or item["id"] in (prev.get("conflicts_with") or []):
        return f"contrast with #{p}: both versions in ONE sentence, each with whose it is"
    if p in (item.get("responds_to") or []) or item["id"] in (prev.get("responds_to") or []):
        return f"the answer to #{p}: say who answers and to what, in the sentence right after it"
    if p in (item.get("bundle") or []):
        g = ", ".join(f"#{x}" for x in item["bundle"])
        return (f"PIECES of one sentence with #{p} ({g}: each repeats the same opening and adds one detail): write them as "
                "ONE sentence, the opening once and then each detail in turn (\"Cyclone Montha made landfall on the Andhra "
                "coast on Tuesday morning, with winds of 100 km/h\"), in parts, one per statement, each part carrying only its "
                "own detail")
    if p in (item.get("parallel") or []):
        g = ", ".join(f"#{x}" for x in item["parallel"])
        return (f"PARALLEL with #{p} ({g}: the same actor doing the same thing to different things): write them as "
                "ONE sentence that names the actor and the verb once and lists each one's part (\"Modi will "
                "inaugurate a park, 40 water bodies and a hydro project\"); if their statuses differ, write it in "
                "parts, one per statement")
    sp, psp = _speaker(item), _speaker(prev)
    if sp and sp == psp:
        return (f"same speaker as #{p}: carry both points with ONE \"said\", or end this one with \", X said.\"; "
                "do not begin it with the name again")
    w, pw = _when(item), _when(prev)
    if w and pw and w != pw:
        return (f"at a different time than #{p} ({w}): give its own date or day (\"On Monday, ...\"); use \"later\" or "
                f"\"then\" only if #{p} is about the same thing, and never to start a paragraph")
    if _words(item["text"]) & _words(prev["text"]):
        return f"same subject as #{p}: refer back to it (\"the company\", \"it\"), do not repeat its full name"
    return None


# ------------------------------------------------------------------ repairs
def strip_filler(text: str) -> str | None:
    """The sentence without its empty opening word, or None when it has none."""
    t = text.strip()
    m = FILLER.match(t) or FILLER_THAT.match(t)
    if not m or len(t) - m.end() < 15:
        return None
    return _cap(t[m.end():])


# a time word that links a sentence to the one before it (owner, Oct 13 2026: "Later, ..." opened paragraphs and
# followed sentences it had nothing to do with)
LINKER = re.compile(r"(?i)^(?:later|then|earlier|afterwards|subsequently|meanwhile)\b\s*,?\s+")


def _start(sent: dict, by_id: dict):
    ts = [(by_id[i].get("time") or {}).get("start") for i in sent.get("ids") or [] if by_id.get(i)]
    try:
        return min(dt.datetime.fromisoformat(t) for t in ts if t)
    except (ValueError, TypeError):
        return None


def earned_linker(prev: dict | None, sent: dict, by_id: dict) -> bool:
    """A \"Later, ...\" is earned only by a sentence right before it, about the same thing, whose statements really
    happened earlier than this one's."""
    if not prev:
        return False
    a, b = _start(prev, by_id), _start(sent, by_id)
    if a is None or b is None or not a < b:
        return False
    return bool(_words(str(prev.get("text") or "")) & _words(str(sent.get("text") or "")))


def strip_linker(text: str) -> str | None:
    t = text.strip()
    m = LINKER.match(t)
    if not m or len(t) - m.end() < 15:
        return None
    return _cap(t[m.end():])


def _leans(text: str) -> bool:
    from . import narrative
    t = text.strip()
    return bool(narrative.LEANS_BACK.search(t) or narrative.PRONOUN_START.match(t))


# "..., reiterating that X" / "..., adding that X": the words that bring a second part in
LEAD_IN = re.compile(r"(?i)^[,;\s]*(?:and\s+)?(?:(?:adding|reiterating|noting|stating|saying|stressing|emphasi[sz]ing|"
                     r"asserting|declaring|affirming|reaffirming|repeating|insisting|maintaining)\s+(?:that\s+)?)?")


def _bare(text: str) -> str:
    return LEAD_IN.sub("", text.strip()).strip()


def _sentence_case(text: str) -> str:
    t = text.strip()
    t = re.sub(r"[,;:\s]+$", "", t) if not re.search(r"[.!?][\"”'’)]*$", t) else t
    t = t[:1].upper() + t[1:] if t else t
    return t if re.search(r"[.!?][\"”'’)]*$", t) else t + "."


def collapse_same_parts(sent: dict, check) -> dict | None:
    """A sentence in coloured parts whose parts say the SAME fact (owner, Oct 11 2026: \"Jammu and Kashmir is an
    integral part of India, reiterating that Jammu and Kashmir is an integral part of India, Bedi said.\", the two
    halves green and purple) says it once: the part the other covers goes, its statements join the one that stays
    (the sentence takes the weakest colour of them, never a stronger one). `check` = every check of narrative.py;
    a collapse that does not pass it leaves the sentence as the writer wrote it. Returns the new sentence or None."""
    from .relate import relate
    parts = [p for p in sent.get("parts") or [] if isinstance(p, dict)]
    if len(parts) < 2:
        return None
    parts = [dict(p, ids=list(p.get("ids") or [])) for p in parts]
    changed = True
    dropped = False
    while changed and len(parts) > 1:
        changed = False
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                r = relate(_bare(parts[i]["text"]), _bare(parts[j]["text"]))
                if r not in ("same", "a_covers_b", "b_covers_a"):
                    continue
                # the covering part stays; for \"same\" the longer one (it keeps the speaker)
                keep, gone = (i, j) if r == "a_covers_b" else (j, i) if r == "b_covers_a" else \
                    ((i, j) if len(parts[i]["text"]) >= len(parts[j]["text"]) else (j, i))
                parts[keep]["ids"] = list(dict.fromkeys(parts[keep]["ids"] + parts[gone]["ids"]))
                del parts[gone]
                changed = dropped = True
                break
            if changed:
                break
    if not dropped:
        return None
    done_parts = []
    for k, p in enumerate(parts):
        t = p["text"].strip()
        if k == 0:
            t = _bare(t)
            t = t[:1].upper() + t[1:]
        if k == len(parts) - 1:
            t = _sentence_case(t)               # the sentence ends with a full stop, not the comma of a dropped part
        done_parts.append(dict(p, text=t))
    out = {k: v for k, v in sent.items() if k != "parts"}
    out["text"] = " ".join(p["text"] for p in done_parts)
    out["ids"] = list(dict.fromkeys(x for p in done_parts for x in p["ids"]))
    if len(done_parts) > 1:
        out["parts"] = done_parts
    return out if check(out) else None


def split_stacked(sent: dict, by_id: dict, check) -> list[dict] | None:
    """One sentence of two clauses joined by \";\" that cites several statements, as two sentences with one claim
    each. Only when: no parts, no quotation, exactly one \";\", the sentence is long (or cites 3+ statements), no
    statement is a dispute or has a partner (contradiction, response, updated figure) among its ids, the second
    half does not lean on the first, every statement is clearly nearer one half than the other (by shared
    words), and each half passes `check` on its own with its own ids."""
    from . import plan
    ids = [i for i in dict.fromkeys(sent.get("ids") or []) if i in by_id]
    text = str(sent.get("text") or "").strip()
    if len(ids) < 2 or sent.get("parts") or text.count(";") != 1 or re.search(r"[\"“”]", text):
        return None
    if not (len(ids) >= 3 or len(text.split()) > STACKED_WORDS):
        return None
    if any(by_id[i].get("verdict") == "disputed" or (plan._links(by_id[i]) & set(ids)) for i in ids):
        return None
    a, b = (x.strip() for x in text.split(";"))
    a, b = a.rstrip(",:"), b
    if not a or not b or len(a.split()) < MIN_HALF or len(b.split()) < MIN_HALF:
        return None
    b = b if re.search(r"[.!?]$", b) else b + "."
    b = _cap(b)
    if grammar.CONNECTIVE.match(b) or _leans(b):
        return None
    a += "."
    wa, wb = _words(a), _words(b)
    ga, gb = [], []
    for i in ids:
        w = _words(by_id[i]["text"])
        na, nb = len(w & wa), len(w & wb)
        if na == nb:
            return None                          # not clearly in one half: do not guess
        (ga if na > nb else gb).append(i)
    if not ga or not gb:
        return None
    out = []
    for half, group in ((a, ga), (b, gb)):
        cand = {k: v for k, v in sent.items() if k != "parts"}
        cand.update(text=half, ids=group)
        if not check(cand):
            return None
        out.append(cand)
    return out


# ------------------------------------------------------------------ polish + stats
def polish(paragraphs: list, by_id: dict, check) -> tuple[list, dict]:
    """The paragraphs with the empty openers taken off and the stacked sentences split, every change checked
    again (`check(sentence) -> bool`, all of narrative's checks) and kept only if it passes. Returns
    (paragraphs, {\"filler\": n, \"split\": n, \"merged\": n})."""
    done = {"filler": 0, "split": 0, "merged": 0}
    out: list = []
    for para in paragraphs:
        new: list = []
        linked = 0                      # earned linkers kept in this paragraph: one at most
        for sent in para:
            if not isinstance(sent, dict) or not sent.get("text"):
                new.append(sent)
                continue
            if not sent.get("parts") and LINKER.match(sent["text"].strip()):
                prev = new[-1] if new and isinstance(new[-1], dict) else None
                if not linked and earned_linker(prev, sent, by_id):
                    linked += 1
                elif (bare_l := strip_linker(sent["text"])):
                    cand = dict(sent, text=bare_l)
                    if check(cand):
                        sent = cand
                        done["linker"] = done.get("linker", 0) + 1
            if sent.get("parts"):
                one = collapse_same_parts(sent, check)
                if one:
                    sent = one
                    done["merged"] += 1
            if not sent.get("parts"):
                bare = strip_filler(sent["text"])
                if bare:
                    cand = dict(sent, text=bare)
                    if check(cand):
                        sent = cand
                        done["filler"] += 1
                two = split_stacked(sent, by_id, check)
                if two:
                    new += two
                    done["split"] += 1
                    continue
            new.append(sent)
        out.append(new)
    return out, done


def stats(paragraphs: list, by_id: dict) -> dict:
    """What code can still see in the finished paragraphs (counted, never enforced): `alike` = two sentences in a row
    opening with the same two words; `long` = sentences past LONG words; `unlinked` = a sentence with nothing that
    links it to the one before (no shared subject or speaker, no leaning pronoun, no time or contrast opening, no
    partner statement)."""
    from . import plan
    alike = long_ = unlinked = n = 0
    # parallel groups the writer kept apart (counted: a high number says the PARALLEL lines are not holding)
    sent_of: dict[int, set[int]] = {}
    k_ = 0
    for para in paragraphs:
        for s_ in para:
            k_ += 1
            for x in s_.get("ids") or []:
                sent_of.setdefault(x, set()).add(k_)
    groups = {tuple(by_id[x]["parallel"]) for x in by_id if by_id[x].get("parallel")}
    apart = sum(1 for g in groups if len(set().union(*[sent_of.get(x, set()) for x in g])) > 1)
    for para in paragraphs:
        texts = [str(s.get("text") or "") for s in para]
        long_ += sum(1 for t in texts if len(t.split()) > LONG)
        for k in range(1, len(para)):
            n += 1
            a, b = texts[k - 1], texts[k]
            if a.lower().split()[:2] and a.lower().split()[:2] == b.lower().split()[:2]:
                alike += 1
            ia = [i for i in para[k - 1].get("ids") or [] if i in by_id]
            ib = [i for i in para[k].get("ids") or [] if i in by_id]
            if (_words(a) & _words(b) or _leans(b) or LINKING_OPEN.match(b.strip())
                    or {_speaker(by_id[i]) for i in ia} & {_speaker(by_id[i]) for i in ib} - {None}
                    or any(plan._links(by_id[i]) & set(ia) for i in ib)):
                continue
            unlinked += 1
    return {"joins": n, "alike": alike, "long": long_, "unlinked": unlinked, "parallel": len(groups),
            "parallel_apart": apart}
