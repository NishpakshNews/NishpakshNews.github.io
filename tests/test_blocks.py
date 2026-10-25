from nishpaksh import blocks

HTML = """<html><body><div><p>%s</p><p>%s</p></div>
<div class="related"><p><a href="/a">Minister resigns after row over exam leak in the northern state today</a></p>
<p><a href="/b">Farmers protest at the border as talks with the government break down again</a></p></div></body></html>""" % (
    " ".join(["The court on Monday ordered the state to file a reply within two weeks and said the matter would be heard again."] * 3),
    " ".join(["Officials said the order would be examined and that the department had already begun reviewing the case file."] * 3))


def test_link_lists_are_dropped_and_prose_kept():
    text = ("The court on Monday ordered the state to file a reply within two weeks.\n"
            "Minister resigns after row over exam leak in the northern state today\n"
            "Farmers protest at the border as talks with the government break down again")
    out, n = blocks.clean(HTML, text)
    assert n == 2 and out == "The court on Monday ordered the state to file a reply within two weeks."


def test_unreadable_page_leaves_text_alone():
    assert blocks.clean("", "x y z") == ("x y z", 0)
