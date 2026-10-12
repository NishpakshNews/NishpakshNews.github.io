"""The writer's sense of "now" (owner, Oct 13 2026: the hourly writer did not know today's date, so its tenses,
\"had\" / \"have\" and \"later\" were guesses, and headlines mixed past, present and future).

  ist_now       the current date and time in India (IST)
  now_line      one block for a prompt: today's date and time, and how to choose a tense from it
  relative      \"today\" / \"yesterday\" / \"3 days ago\" / \"tomorrow\" / \"in 2 days\" for a statement's date, so the writer
                does not have to work out the tense from a date
No model in it.
"""
from __future__ import annotations

import datetime as dt

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

TENSE_RULES = (
    "Choose every tense from NOW, not from the order of the statements:\n"
    "- an event dated before now is told in the simple past (\"declined\", \"sent\"); an event dated today that has\n"
    "  happened is the same; an event dated after now is future (\"will hear\", \"is due to\"), never past.\n"
    "- \"had\" (past perfect) ONLY for something that happened before another past event named in the SAME sentence.\n"
    "  \"has / have\" (present perfect) ONLY for something still true or still continuing now. Never use either for a\n"
    "  plain past event: \"Kant declined\", not \"Kant had declined\" / \"Kant has declined\".\n"
    "- \"later\", \"then\", \"earlier\", \"afterwards\": ONLY when the sentence right before it in the same paragraph is about the\n"
    "  same thing and the two statements really are at different times. Never as the first word of a paragraph, never\n"
    "  after an unrelated sentence, at most once in a paragraph. Otherwise give the date or day itself (\"On Monday\")\n"
    "  or no time word at all.\n"
    "- a day name or date is written as given in the statement; \"yesterday\" / \"today\" / \"tomorrow\" only as the tag\n"
    "  after the statement's \"when\" says."
)


def ist_now(now: dt.datetime | None = None) -> dt.datetime:
    """The current time in IST; a naive `now` is read as UTC (the database clock)."""
    if now is None:
        return dt.datetime.now(dt.timezone.utc).astimezone(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    return now.astimezone(IST)


def now_line(now: dt.datetime | None = None) -> str:
    n = ist_now(now)
    return (f"NOW: it is {n.strftime('%A %-d %B %Y')}, {n.strftime('%H:%M')} IST (India). You are writing this "
            f"article at this moment.\n{TENSE_RULES}\n")


def relative(start: str | None, now: dt.datetime | None = None) -> str:
    """How far a statement's date is from today (IST), in words; \"\" when it has no readable date.
    A date with no zone is read as an Indian date."""
    if not start:
        return ""
    try:
        d = dt.datetime.fromisoformat(str(start))
    except ValueError:
        return ""
    d = d.astimezone(IST) if d.tzinfo else d
    gap = (d.date() - ist_now(now).date()).days
    if gap == 0:
        return "today"
    if gap == -1:
        return "yesterday"
    if gap == 1:
        return "tomorrow"
    return f"{-gap} days ago" if gap < 0 else f"in {gap} days"
