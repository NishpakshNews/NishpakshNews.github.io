"""The home card shows the article's opening in the page's section order (owner, Oct 15 2026)."""
from nishpaksh.feed import _card_text, page_order


def _p(t):
    return [{"text": t, "class": "established"}]


def test_card_follows_the_page_order_not_the_stored_order():
    # written in the old order: news, background, explained, happened, numbers, say
    paras = [_p("lead"), _p("bg"), _p("expl"), _p("hap"), _p("num"), _p("say")]
    keys = ["news", "background", "explained", "happened", "numbers", "say"]
    assert page_order(paras, keys) == [0, 1, 3, 5, 4, 2]
    assert [p[0]["t"] for p in _card_text(paras, keys)] == ["lead", "bg", "hap", "say", "num", "expl"]


def test_no_keys_keeps_the_stored_order_and_the_limit_holds():
    paras = [_p(str(i)) for i in range(12)]
    assert [p[0]["t"] for p in _card_text(paras)] == [str(i) for i in range(9)]
    # a paragraph with no key of its own belongs to the section before it
    assert page_order([_p("a"), _p("b"), _p("c")], ["news", "say", None]) == [0, 1, 2]
