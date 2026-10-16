"""Colour notifications (notify.line_classes / colour_changes / queue_colours; owner Oct 16 2026)."""
import datetime as dt

from nishpaksh import notify as N


def page(*classes, struck=()):
    return {"narrative": {"paragraphs": [[{"text": f"s{k}", "class": c, **({"struck": True} if k in struck else {})}
                                          for k, c in enumerate(classes)]]}}


def test_lines_turning_a_colour_are_counted_once_and_struck_lines_are_skipped():
    before = N.line_classes(page("single", "developing", "single", "single"))
    now = N.line_classes(page("established", "established", "disputed", "single", "single"))
    assert N.colour_changes(before, now) == {"established": 2, "disputed": 1}       # a new line is not a change
    assert "0.1" not in N.line_classes(page("single", "single", struck=(1,)))
    parts = {"narrative": {"paragraphs": [[{"text": "a", "class": "single",
                                            "parts": [{"text": "x", "class": "established"}, {"text": "y", "class": "single"}]}]]}}
    assert N.line_classes(parts) == {"0.0.0": "established", "0.0.1": "single"}


def test_one_notification_per_article_per_hour_for_the_colours_a_reader_picked(monkeypatch):
    state, sent = {}, []
    rows = [{"story_id": 7, "headline_en": "Bridge falls", "headline_hi": "पुल गिरा", "payload_en": page("single", "single")}]

    class S:
        def rows(self, q):
            text = str(q)
            if "follows" in text:
                return [{"reader": "r1", "key": "established"}, {"reader": "r2", "key": "false"}]
            return rows
    monkeypatch.setattr(N, "_state", lambda store, k: state.get(k, {}))
    monkeypatch.setattr(N, "_set_state", lambda store, k, v: state.__setitem__(k, v))
    monkeypatch.setattr(N, "_reader_langs", lambda store, rs: {"r1": "en"})
    monkeypatch.setattr(N, "add_notification", lambda store, reader, kind, ref, title, body, url, sid=None:
                        sent.append((reader, kind, ref, body)) or True)
    now = dt.datetime(2026, 10, 16, 12, 0)
    assert N.queue_colours(S(), now) == 0                                            # first sight: recorded only
    rows[0]["payload_en"] = page("established", "established")
    assert N.queue_colours(S(), now) == 1
    assert sent == [("r1", "colour", "7@2026-10-16T17", "2 lines now established")]
