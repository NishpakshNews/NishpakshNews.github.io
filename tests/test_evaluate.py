from nishpaksh.tools import evaluate as ev


def test_recall_at_precision_takes_the_best_threshold_that_holds():
    r = ev.recall_at_precision([0.9, 0.8, 0.7, 0.6, 0.5], [True, True, False, True, False], target=1.0)
    assert r["recall"] == round(2 / 3, 4) and r["threshold"] == 0.8


def test_no_positives_is_reported_not_divided():
    assert ev.recall_at_precision([0.1], [False])["recall"] is None


def test_scoring_stored_pairs_runs_end_to_end():
    rows = [{"a": f"The company reported a profit of {n} crore", "b": f"Profit of the company was {n} crore", "label": True}
            for n in range(500, 540)] + \
           [{"a": f"Police arrested {w} in Delhi", "b": f"Police released {w} in Pune", "label": False}
            for w in ("Rakesh", "Anil", "Vijay", "Sunil", "Manoj", "Ravi", "Ajay", "Deepak", "Sanjay", "Mohan") * 3]
    out = ev.score_pairs(rows)
    assert out["pairs"] == 70 and "code_verdict" in out and "fellegi_sunter" in out


def test_writing_counts_only_articles_with_an_inspector():
    pages = [{"narrative": {"flow": {"inspector": {"repeats": 2, "unintroduced": 1}}}}, {"narrative": {}}]
    w = ev.writing(pages)
    assert w["articles"] == 1 and w["repeats"] == 2 and w["unintroduced"] == 1


def test_labels_are_recovered_from_stored_same_checks():
    import hashlib
    import json

    from nishpaksh.tools import evaluate as e

    class R(list):
        def all(self):
            return self

    class C:
        def execute(self, q, p=None):
            if "same_checks" in str(q):
                k = hashlib.sha256(json.dumps(["B text", "A text"]).encode()).hexdigest()[:16]
                return R([(1, {k: False, "fzz": True})])
            return [("A text",), ("B text",), ("C text",)]

    got = e.labels_from_answers(C())
    assert got == [{"a": "B text", "b": "A text", "label": False}]       # the "f..." fold answers are not labels
