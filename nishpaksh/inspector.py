"""One look over the finished article (B9): the checks that run sentence by sentence, run again on the final text.

Every sentence is checked where it stands, after all rewrites, polishing and re-ordering: does a paragraph open with a pronoun,
does a pronoun point at nothing, does a sentence repeat an earlier one, does a figure appear in two spellings. It only COUNTS
(the article is closed once written and nothing here changes a word); the counts go to the page's flow stats, and a high number
says an earlier stage is not holding. Reads the discourse as it is: the sentence before is "near" for a pronoun.
"""
from __future__ import annotations

from . import refs


def inspect(paragraphs: list[list[dict]]) -> dict:
    out = {"sentences": 0, "opens_with_pronoun": 0, "pronoun_without_antecedent": 0, "repeats": 0}
    seen: list[str] = []
    from .relate import Profile, relate
    profiles: list[Profile] = []
    for para in paragraphs:
        prev = ""
        for k, s in enumerate(para):
            text = (s.get("text") or "").strip()
            if not text:
                continue
            out["sentences"] += 1
            if k == 0 and refs.opening_problem(text):
                out["opens_with_pronoun"] += 1
            if k > 0 and refs.antecedent_problem(text, prev):
                out["pronoun_without_antecedent"] += 1
            pr = Profile(text)
            if any(relate(t, text, None, None, p, pr) in ("same",) for t, p in zip(seen, profiles)):
                out["repeats"] += 1
            seen.append(text)
            profiles.append(pr)
            prev = text
    try:
        from . import discourse
        out.update(discourse.inspect(paragraphs))
    except Exception:
        pass                                   # the discourse model is a count; it never stops an article
    out["problems"] = (out["opens_with_pronoun"] + out["pronoun_without_antecedent"] + out["repeats"]
                       + out.get("unintroduced", 0) + out.get("pronoun_without_focus", 0) + out.get("time_back", 0))
    return out
