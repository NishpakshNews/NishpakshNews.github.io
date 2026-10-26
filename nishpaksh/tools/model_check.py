"""Do all the models and libraries the pipeline relies on load and work? (workflow `audit`, tool `model_check`)

Calls the PIPELINE'S OWN entry points (nli.both, embed.vectors, nlp.*, agreement, langcheck, bodies, coref, focus), never the
libraries directly, so a fall-back (TF-IDF for embeddings, the small spaCy model, no LanguageTool) shows as "fallback", not as ok.
One diagnostics row of kind 'model_check': per component {ok, fallback, sec, detail|error}. No model quota is used.
`snapshot()` reads module state only (no loading); run.py stores it in runs.stats["models"] after every run.
"""
from __future__ import annotations

import json
import os
import time


def timed(fn) -> dict:
    t = time.time()
    try:
        out = fn() or {}
        out.setdefault("ok", True)
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    out["sec"] = round(time.time() - t, 1)
    return out


def nli_check() -> dict:
    from .. import nli
    if not nli.available():
        return {"ok": False, "error": "NLI model did not load"}
    r = nli.both([("Police arrested the minister on Monday.", "The minister was arrested."),
                  ("Police arrested the minister.", "Police did not arrest the minister.")])
    if not r or r[0] is None or r[1] is None:
        return {"ok": False, "error": "no answer"}
    ent = nli.same([("Police arrested the minister on Monday.", "The minister was arrested.")])
    con = nli.conflict([("Police arrested the minister.", "Police did not arrest the minister.")])
    return {"model": nli.MODEL, "entails": ent, "conflict": con, "ok": con == ["cannot_both_be_true"] and ent == [True]}


def embed_check() -> dict:
    from .. import embed
    v, how = embed.vectors(["Police arrested the minister.", "The minister was detained by police.", "Rain flooded the city."])
    s = (v @ v.T)
    near, far = float(s[0, 1]), float(s[0, 2])
    return {"how": how, "fallback": how != "bi-encoder", "dim": int(v.shape[1]), "similar": round(near, 2), "unrelated": round(far, 2),
            "ok": how == "bi-encoder" and near > far}


def spacy_check() -> dict:
    from .. import nlp
    pipe = nlp.pipeline()
    if pipe is None:
        return {"ok": False, "error": "no spaCy model"}
    name = pipe.meta.get("name", "?")
    text = "Union Home Minister Amit Shah said on Monday that police arrested 18 people in Delhi."
    ents, toks, chunks, cl = nlp.ents(text), nlp.parse(text), nlp.noun_chunks(text), nlp.clauses(text)
    return {"model": f"{pipe.meta.get('lang')}_{name}", "fallback": name != "core_web_lg",
            "entities": len(ents or []), "tokens": len(toks or []), "chunks": len(chunks or []), "clauses": len(cl or []),
            "ok": bool(ents) and bool(toks) and name == "core_web_lg"}


def lemminflect_check() -> dict:
    from lemminflect import getInflection
    f = getInflection("be", "VBD")
    return {"result": list(f or []), "ok": bool(f)}


def langtool_check() -> dict:
    from .. import langcheck
    if not langcheck.available():
        return {"ok": False, "error": "LanguageTool unavailable (Java or download); counted-only, the pipeline goes on"}
    r = langcheck.issues("He go to school yesterday.")
    return {"issues": len(r or []), "ok": r is not None}


def wikidata_check() -> dict:
    from .. import bodies
    r = bodies.resolve("Supreme Court of India")
    if r is None:
        return {"ok": False, "error": "Wikidata could not be asked"}
    return {"key": getattr(r, "key", None), "ok": getattr(r, "key", None) is not None}


def coref_check() -> dict:
    from .. import coref
    r = coref.dangling("Rahul met Priya. He said she was late.")
    return {"result": r, "ok": r is not None}


def faces_check() -> dict:
    from .. import focus
    cv = focus._cv()
    if cv is None:
        return {"ok": False, "error": "opencv not installed"}
    exists = os.path.exists(focus.MODEL)
    det = None
    if exists:
        det = cv.FaceDetectorYN.create(str(focus.MODEL), "", (320, 320))
    return {"opencv": cv.__version__, "model_file": exists, "ok": exists and det is not None}


def hf_cache_check() -> dict:
    root = os.path.expanduser(os.getenv("HF_HOME", "~/.cache/huggingface")) + "/hub"
    names = sorted(d for d in os.listdir(root) if d.startswith("models--")) if os.path.isdir(root) else []
    return {"models": names, "ok": bool(names)}


CHECKS = [("nli", nli_check), ("embed", embed_check), ("spacy", spacy_check), ("lemminflect", lemminflect_check),
          ("langtool", langtool_check), ("wikidata", wikidata_check), ("coref", coref_check), ("faces", faces_check),
          ("hf_cache", hf_cache_check)]


def snapshot() -> dict:
    """What is loaded right now in this process (no loading, no cost): True loaded, False tried and failed, None never asked."""
    def state(mod, attr):
        v = getattr(mod, attr, None)
        return None if v is None else bool(v)
    out = {}
    try:
        from .. import nli, embed, nlp, langcheck
        out = {"nli": state(nli, "_model"), "embed": state(embed, "_model"), "spacy": state(nlp, "_nlp"), "langtool": state(langcheck, "_tool")}
        p = getattr(nlp, "_nlp", None)
        if p:
            out["spacy_model"] = p.meta.get("name")
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:100]
    return out


def main() -> None:
    report = {name: timed(fn) for name, fn in CHECKS}
    report["_summary"] = {"failed": [n for n, r in report.items() if not r.get("ok")],
                          "fallback": [n for n, r in report.items() if r.get("fallback")]}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    try:
        from sqlalchemy import text as sql
        from ..config import database_url
        from ..db import Store
        store = Store(database_url())
        with store.readers.engine.begin() as c:
            c.execute(sql("insert into diagnostics (kind, report) values ('model_check', :r)"), {"r": json.dumps(report, ensure_ascii=False)})
    except Exception as e:  # noqa: BLE001
        print("diagnostics not written:", e)


if __name__ == "__main__":
    main()
