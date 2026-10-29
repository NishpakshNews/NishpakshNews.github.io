"""Share pages: what a chat app reads when an article's link is sent (nishpaksh/sharepages.py)."""
import re

from nishpaksh import sharepages as sp

PARAS = [[{"t": "Police arrested two men in Pune on Monday.", "c": "established"},
          {"t": "The pair were produced before a court.", "c": "single"}],
         [{"t": "A third suspect is still at large and the search continues across the state.", "c": "single"}]]


def test_clean_addresses():
    assert sp.share_path(123, "en") == "/s/123/"
    assert sp.share_path("123", "hi") == "/hi/s/123/"


def test_description_is_whole_sentences_within_the_limit():
    d = sp.description(PARAS, limit=100)
    assert d == "Police arrested two men in Pune on Monday. The pair were produced before a court."
    assert len(sp.description(PARAS, limit=60)) <= 60
    assert sp.description([]) == ""


def test_description_cuts_one_very_long_sentence_on_a_word():
    d = sp.description([[{"t": "word " * 100}]], limit=50)
    assert d.endswith("…") and len(d) <= 50


def test_page_has_the_preview_tags_and_escapes_the_headline():
    html = sp.render(7, "en", 'Rs 5 "crore" <seized> & more', "Opening.", "https://img.example/a.jpg?x=1&y=2")
    assert '<meta property="og:title" content="Rs 5 &quot;crore&quot; &lt;seized&gt; &amp; more">' in html
    assert 'content="https://img.example/a.jpg?x=1&amp;y=2"' in html
    assert f'<meta property="og:url" content="{sp.SITE}/s/7/">' in html
    assert 'name="twitter:card" content="summary_large_image"' in html
    assert 'location.replace("/?lang=en#/story/7")' in html
    assert "<seized>" not in html


def test_hindi_page_points_at_the_hindi_article():
    html = sp.render(7, "hi", "शीर्षक", "विवरण", sp.FALLBACK_IMAGE)
    assert 'lang="hi"' in html and f"{sp.SITE}/hi/s/7/" in html and "lang=hi#/story/7" in html


def test_picture_falls_back_to_the_site_icon():
    assert sp.image_for(None) == sp.FALLBACK_IMAGE
    assert sp.image_for({"src": "javascript:x"}) == sp.FALLBACK_IMAGE
    assert sp.image_for({"src": "https://o.example/p.jpg"}) == "https://o.example/p.jpg"


def test_write_makes_a_folder_per_story_and_removes_gone_ones(tmp_path):
    manifest = {"1": {"en": {"h": "One", "paras": PARAS}, "hi": {"h": "एक", "paras": PARAS}},
                "2": {"en": {"h": "Two", "paras": PARAS}, "hi": None}}
    pics = {"1": {"src": "https://o.example/1.jpg"}}
    assert sp.write(tmp_path, manifest, pics, ["1", "2"]) == 3
    page = (tmp_path / "s" / "1" / "index.html").read_text(encoding="utf-8")
    assert "https://o.example/1.jpg" in page
    assert sp.FALLBACK_IMAGE in (tmp_path / "s" / "2" / "index.html").read_text(encoding="utf-8")
    assert (tmp_path / "hi" / "s" / "1" / "index.html").exists() and not (tmp_path / "hi" / "s" / "2").exists()
    assert sp.write(tmp_path, manifest, pics, ["1"]) == 2
    assert not (tmp_path / "s" / "2").exists()
