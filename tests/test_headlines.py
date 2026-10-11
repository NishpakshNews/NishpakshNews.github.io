"""Headlines that make the reader want the article (owner, Oct 12 2026): weak, old-sounding, and a bare name of a
person nobody knows. Checks by code on what the model writes; the model is only asked for three candidates."""
from nishpaksh.news import (HEADLINE_PROMPT, _opening_name_problem, headline_problem, headline_score, known_names,
                            write_headline)

FACTS = ("The Supreme Court ordered actor Rajpal Yadav to pay Rs 5 crore. Rajpal Yadav said he would "
         "appeal. Prime Minister Narendra Modi said the scheme will help farmers. Rahul Gandhi said the order "
         "was wrong. Sahil Wakode, a first-year student at IIT Bombay, was found dead in his hostel room. "
         "Ramesh Kumar, 34, was produced before the court in Kotdwar.")


def _problem(h):
    return headline_problem(h, FACTS.lower(), set(), frozenset(), FACTS)


def test_a_headline_may_not_open_with_a_name_readers_do_not_know():
    assert "opens with 'Rajpal Yadav'" in _problem("Rajpal Yadav ordered to pay Rs 5 crore by Supreme Court")
    assert "(actor)" in _problem("Rajpal Yadav's Rs 5 crore order stands in Supreme Court")
    assert "opens with 'Sahil Wakode'" in _problem("Sahil Wakode found dead in hostel room")      # a stranger, "Name, a ..."
    assert "opens with 'Ramesh Kumar'" in _problem("Ramesh Kumar produced before Kotdwar court")  # "Name, 34,"


def test_who_they_are_first_or_the_event_first_is_fine():
    assert _problem("Actor Rajpal Yadav ordered to pay Rs 5 crore by Supreme Court") is None
    assert _problem("Supreme Court orders actor Rajpal Yadav to pay Rs 5 crore") is None
    assert _problem("IIT Bombay first-year student found dead in hostel room") is None
    assert _problem("Kotdwar gym trainer produced before court") is None


def test_names_every_indian_knows_may_open_a_headline():
    full, surnames = known_names()
    assert "narendra modi" in full and "modi" in surnames and "gandhi" not in surnames
    assert _problem("Narendra Modi says scheme will help farmers") is None
    assert _problem("Modi says scheme will help farmers") is None
    assert _problem("Rahul Gandhi says order was wrong") is None
    assert _opening_name_problem("anything", "") is None                    # no statements: nothing to judge


def test_teasers_questions_and_old_news_are_rejected():
    assert "plainly" in _problem("What we know about the Rajpal Yadav case")
    assert "plainly" in _problem("Why was Rajpal Yadav ordered to pay?")
    assert "plainly" in _problem("Supreme Court orders Rajpal Yadav to pay Rs 5 crore!")
    assert "past" in _problem("Supreme Court had earlier ordered actor Rajpal Yadav to pay")
    assert "past" in _problem("Supreme Court previously ordered actor Rajpal Yadav to pay")


def test_a_headline_about_the_newest_development_scores_higher():
    news = "ED registered a case against Bluestone Realty on Monday."
    latest = "ED arrested Bluestone Realty founder Arun Mehta on Wednesday."
    old = "ED registers case against Bluestone Realty over loan fraud"
    new = "ED arrests Bluestone Realty founder Arun Mehta"
    assert headline_score(new, news, latest) > headline_score(old, news, latest)


class _Res:
    def __init__(self, data):
        self.data = data


class _Router:
    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def call(self, tier, prompt, json_out=False, max_output_tokens=None):
        self.prompts.append(prompt)
        return _Res(self.replies.pop(0))


def _items():
    news = {"id": 1, "text": "The Supreme Court ordered actor Rajpal Yadav to pay Rs 5 crore.", "n_sources": 3, "role": "core"}
    latest = {"id": 2, "text": "Rajpal Yadav said he would appeal.", "n_sources": 1, "role": "core"}
    return news, latest, {1: news, 2: latest}


def test_write_headline_gives_the_model_the_latest_fact_and_picks_a_good_one():
    news, latest, items = _items()
    router = _Router([{"headlines": ["Rajpal Yadav ordered to pay Rs 5 crore",           # unknown name first: out
                                     "What we know about Rajpal Yadav's case",            # teaser: out
                                     "Supreme Court orders actor Rajpal Yadav to pay Rs 5 crore"]}])
    h = write_headline(router, news, items, "The Supreme Court ordered actor Rajpal Yadav to pay Rs 5 crore.",
                       set(), latest=latest)
    assert h == "Supreme Court orders actor Rajpal Yadav to pay Rs 5 crore"
    assert "LATEST (the newest development, headline THIS one): Rajpal Yadav said he would appeal." in router.prompts[0]
    assert len(router.prompts) == 1


def test_write_headline_asks_again_with_the_reasons_when_all_three_fail():
    news, _, items = _items()
    bad = {"headlines": ["Rajpal Yadav ordered to pay Rs 5 crore", "Why was Rajpal Yadav told to pay?", "Rajpal Yadav loses"]}
    good = {"headlines": ["Supreme Court orders actor Rajpal Yadav to pay Rs 5 crore"]}
    router = _Router([bad, good])
    assert write_headline(router, news, items, "x", set()) == "Supreme Court orders actor Rajpal Yadav to pay Rs 5 crore"
    assert "These were rejected" in router.prompts[1] and "opens with 'Rajpal Yadav'" in router.prompts[1]
    assert "LATEST" not in router.prompts[0].split("THE NEWS:")[1].split("The article opens")[0]


def test_the_prompt_is_still_found_by_the_fake_backend_and_fills_in():
    assert HEADLINE_PROMPT.startswith("Write THREE different headlines")
    text = HEADLINE_PROMPT.format(dispute="", thread="", news="N", newest="THE NEWS", latest="", lead="L", others="- o")
    assert "THE NEWS: N" in text and "{" not in text.replace("{{", "").replace("}}", "").split("Reply with JSON only")[0]
