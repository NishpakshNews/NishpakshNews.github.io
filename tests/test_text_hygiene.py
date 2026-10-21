"""Regression checks for source decoding and mojibake repair."""
from nishpaksh.text_hygiene import clean_source_text, decode_page


def test_utf8_is_preferred_when_http_has_no_charset():
    raw = "<html><body>दिल्ली में बारिश — News</body></html>".encode("utf-8")
    assert "दिल्ली में बारिश" in decode_page(raw, "text/html", "ISO-8859-1")


def test_declared_legacy_encoding():
    raw = b'<meta charset="windows-1252">It\x92s done.'
    assert "It’s done." in decode_page(raw, "text/html", "utf-8")


def test_repair_mojibake_without_rephrasing():
    assert clean_source_text("Relianceâ€™s decision") == "Reliance’s decision"
    assert clean_source_text("दिल्ली में बारिश") == "दिल्ली में बारिश"


def test_utf8_bom_and_empty():
    assert decode_page(b"\xef\xbb\xbfhello") == "hello"
    assert decode_page(b"") == ""
