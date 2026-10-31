import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from nishpaksh import namevariants as nv
D = json.loads((pathlib.Path(__file__).parent / "labels/name_variants.json").read_text())["pairs"]

def run():
    rows = []
    for p in D:
        back_a = [{"lang": "hi", "src": p["hi_a"]}] if p.get("hi_a") else []
        r = nv.decide(p["a"], p["b"], back_a, [])
        rows.append((p, r))
    return rows

def test_no_false_same():
    bad = [(p["id"], r) for p, r in run() if p["want"] != "same" and r["verdict"] == "same"]
    assert not bad, bad

def test_true_variants_found():
    miss = [(p["id"], r) for p, r in run() if p["want"] == "same" and r["verdict"] != "same"]
    assert not miss, miss

def test_live_case_goes_to_reader():
    r = dict((p["id"], r) for p, r in run())["preservation"]
    assert r["verdict"] in ("ask", "unsure") and r["verdict"] != "same", r

def test_term_memory_and_leak():
    m = nv.TermMemory()
    assert m.learn_source("एपी सिंह ( Ex IAF Chief AP Singh ) ने कहा") == 1
    txt, done = m.fix_leak("Chief एपी सिंह said")
    assert "AP Singh" in txt and done[0]["rank"] == nv.RANK_BRACKET, (txt, done)
    t2, _ = nv.TermMemory().fix_leak("Amar प्रीत Singh")
    assert "Preet" in t2 or "Prit" in t2, t2

def test_choose_form():
    f = {"Preservation": [{"lang": "en", "outlet": "A"}, {"lang": "en", "outlet": "B"}], "Conservation": [{"lang": "hi", "outlet": "C"}]}
    assert nv.choose_form(f) == "Preservation"
    assert nv.choose_form({"x": [{"lang": "hi", "outlet": "a"}], "y": [{"lang": "hi", "outlet": "b"}]}) is None

if __name__ == "__main__":
    for p, r in run():
        print(f'{p["id"]:16} want={p["want"]:7} got={r["verdict"]:7} {r.get("route")} {r.get("slot")} {r.get("similarity","")}')
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try: f(); print("PASS", n)
            except AssertionError as e: print("FAIL", n, e)
