"""Can the established libraries and models run on the free GitHub runner? (Notes B1, B3, B7, B9, B16, B19, B21.)
Tries each candidate on a few real sentence pairs and prints: installed or not, load time, time per call, the answer.
Nothing here touches the pipeline. Run: workflow `audit`, tool `stack_probe` (the workflow installs the extras)."""
from __future__ import annotations

import json
import time

PAIRS = [   # (a, b, what a good system says)
    ("At least 9 people died in the stampede on Saturday.", "Nine people were killed in the stampede on Sunday.", "date conflict, same event"),
    ("Police arrested Harjit Singh on Friday.", "Police did not arrest Harjit Singh on Friday.", "contradiction"),
    ("Defence Minister Rajnath Singh said the army is ready.", "Rajnath Singh said the army was ready.", "same"),
    ("The repo rate was cut by 25 basis points.", "The RBI lowered the repo rate by 0.25 per cent.", "same"),
    ("Mamata Banerjee addressed the rally.", "Abhishek Banerjee addressed the rally.", "different people"),
]
HI = [("भगदड़ में कम से कम नौ लोगों की मौत हुई।", "At least nine people died in the stampede.", "same, cross-language")]
TEXT = "Chief Electoral Officer Navdeep Rinwa said it. Parvinder Singh Jhota was shot. He died. The scheme was announced by the Centre."


def timed(fn):
    t = time.time()
    try:
        r = fn()
        return {"ok": True, "result": r, "sec": round(time.time() - t, 2)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "sec": round(time.time() - t, 2)}


def spacy_probe():
    import spacy
    nlp = spacy.load("en_core_web_sm")
    d = nlp(TEXT)
    return {"ents": [(e.text, e.label_) for e in d.ents], "deps": [(t.text, t.dep_, t.head.text) for t in d if t.dep_ in ("nsubj", "nsubjpass", "appos", "expl")][:12]}


def rapidfuzz_probe():
    from rapidfuzz import fuzz
    return [(a, b, fuzz.token_sort_ratio(a, b)) for a, b in [("Harjit Singh", "Harjeet Singh"), ("Bhim Singh", "Harjit Singh"), ("Yash Vir", "Yashvir")]]


def nli_probe(model="MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"):
    from transformers import pipeline
    t = time.time()
    clf = pipeline("text-classification", model=model, top_k=None, device=-1)
    load = round(time.time() - t, 1)
    out = []
    for a, b, want in PAIRS + HI:
        t = time.time()
        r = clf({"text": a, "text_pair": b})
        r = r[0] if r and isinstance(r[0], list) else r
        out.append({"want": want, "a": a, "b": b, "scores": {x["label"]: round(x["score"], 2) for x in r}, "sec": round(time.time() - t, 2)})
    return {"load_sec": load, "pairs": out}


def embed_probe(model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
    from sentence_transformers import SentenceTransformer, util
    t = time.time()
    m = SentenceTransformer(model, device="cpu")
    load = round(time.time() - t, 1)
    out = []
    for a, b, want in PAIRS + HI:
        e = m.encode([a, b])
        out.append({"want": want, "cos": round(float(util.cos_sim(e[0], e[1])), 2)})
    return {"load_sec": load, "pairs": out}


def splink_probe():
    import splink
    return {"version": getattr(splink, "__version__", "?")}


def coref_probe():
    import spacy
    import coreferee  # noqa: F401
    nlp = spacy.load("en_core_web_sm")
    nlp.add_pipe("coreferee")
    d = nlp("Parvinder Singh Jhota was shot on Friday. He died on the way to hospital. The scheme was announced. It was launched in 2019.")
    return str(d._.coref_chains)


def main() -> None:
    report = {name: timed(fn) for name, fn in [("spacy", spacy_probe), ("rapidfuzz", rapidfuzz_probe), ("splink", splink_probe),
                                               ("coreferee", coref_probe), ("nli_mdeberta", nli_probe), ("embed_minilm", embed_probe)]}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    try:
        from sqlalchemy import text as sql
        from ..config import database_url
        from ..db import Store
        store = Store(database_url())
        with store.readers.engine.begin() as c:
            c.execute(sql("insert into diagnostics (kind, report) values ('stack_probe', :r)"), {"r": json.dumps(report, ensure_ascii=False)})
    except Exception as e:  # noqa: BLE001
        print("diagnostics not written:", e)


if __name__ == "__main__":
    main()
