from nishpaksh import nli
from nishpaksh.tools import merge_audit as ma


def test_classify_reads_both_directions_and_conflict():
    hi, lo, con = (0.95, 0.03, 0.02), (0.1, 0.8, 0.1), (0.02, 0.1, 0.88)
    assert ma.classify("ask", hi, hi, nli) == "same"
    assert ma.classify("ask", hi, lo, nli) == "a_says_b"
    assert ma.classify("ask", lo, hi, nli) == "b_says_a"
    assert ma.classify("ask", lo, lo, nli) == "neutral"
    assert ma.classify("ask", con, lo, nli) == "conflict"
    assert ma.classify("different", hi, hi, nli) == "different"      # code's veto stands
    assert ma.classify("ask", None, hi, nli) == "unread"


def test_clusters_counts_components():
    assert ma.clusters(5, [(0, 1), (1, 2)]) == 3
    assert ma.clusters(3, []) == 3
