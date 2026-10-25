"""A model of the article as a reader has read it so far (B9): who has been introduced, who is the topic, where the time is.

One pass over the sentences in reading order, with the entity table of the article (entities.py) and the parse:

    introduced   a person is introduced by a mention that carries the full name; a surname alone before that is a
                 reference to somebody the reader has not met
    focus        the person the last sentence was about (centering): a he / she subject with no focus points at nothing
    cursor       the newest date written so far in the paragraph; a sentence dated earlier with no word saying it looks back
                 ("earlier", "previously", "had") moves the story backwards without telling the reader

Every sentence is stepped and the problems are named; nothing here rewrites a word (the article is closed once written):
the writer's checks and the inspector ask it, and the counts say which earlier stage is not holding.
"""
from __future__ import annotations

import re

from . import entities, nlp, when

LOOKS_BACK = re.compile(r"(?i)\b(earlier|previously|before|had|last (?:year|month|week)|in \d{4}|ago|since)\b")
PRONOUNS = {"he", "she"}


class Discourse:
    def __init__(self, table: entities.EntityTable | None = None):
        self.table = table if table is not None else entities.EntityTable()
        self.introduced: set[str] = set()
        self.focus: str | None = None
        self.cursor: tuple | None = None
        self.said = 0

    @classmethod
    def of(cls, paragraphs: list[list[dict]]) -> "Discourse":
        table = entities.EntityTable()
        for para in paragraphs:
            for s in para:
                if s.get("text"):
                    table.add_text(s["text"])
        table.build()
        return cls(table)

    def new_paragraph(self) -> None:
        self.cursor = None

    def _people(self, text: str) -> list[tuple[int, entities.Entity, int]]:
        """(position, entity, words in this mention) for every person the sentence names, in order: the written forms
        the article's entity table holds for each person (the full name, a shorter form, the surname), longest first."""
        found: list[tuple[int, int, entities.Entity, int]] = []
        for ent in self.table.persons():
            if ent.ambiguous:
                continue
            forms = {m.text for m in ent.mentions if m.tokens}
            if ent.surname:
                forms.add(ent.surname)
            for f in sorted(forms, key=len, reverse=True):
                for m in re.finditer(rf"(?<![\w-]){re.escape(f)}(?![\w-])", text):
                    found.append((m.start(), m.end(), ent, len(f.split())))
        found.sort(key=lambda x: (x[0], -(x[1] - x[0])))
        out, edge = [], -1
        for st, en, ent, words in found:          # leftmost, longest: "Humayun Kabir" is not also "Kabir"
            if st >= edge:
                out.append((st, ent, words))
                edge = en
        return out

    def step(self, text: str) -> list[str]:
        problems: list[str] = []
        people = self._people(text)
        for _, ent, words in people:
            if words < 2 and len(ent.fullest.tokens) >= 2 and ent.key not in self.introduced:
                problems.append("unintroduced")
            if words >= 2 or len(ent.fullest.tokens) < 2:
                self.introduced.add(ent.key)
        toks = nlp.parse(text) or []
        if self.said and self.focus is None and any(t.dep == "nsubj" and t.text.lower() in PRONOUNS for t in toks):
            problems.append("pronoun_without_focus")
        d = when.date_of(text)
        if d and d[0] and d[1] and d[2]:
            if self.cursor and d < self.cursor and not LOOKS_BACK.search(text):
                problems.append("time_back")
            if not self.cursor or d > self.cursor:
                self.cursor = d
        if people:
            self.focus = people[0][1].key
        self.said += 1
        return problems


def inspect(paragraphs: list[list[dict]]) -> dict:
    dis = Discourse.of(paragraphs)
    out = {"unintroduced": 0, "pronoun_without_focus": 0, "time_back": 0}
    for para in paragraphs:
        dis.new_paragraph()
        for s in para:
            text = (s.get("text") or "").strip()
            if text:
                for p in dis.step(text):
                    out[p] += 1
    return out
