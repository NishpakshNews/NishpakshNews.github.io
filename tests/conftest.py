import dataclasses

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "settle: keep the wait for coverage to settle (editions.py)")
    config.addinivalue_line("markers", "carry: keep the carry-over of unused hourly allowances (carry.py)")


@pytest.fixture(autouse=True)
def two_databases(monkeypatch, tmp_path):
    """Production keeps reader tables and run logs in Supabase and the newsroom in the job's own Postgres
    (db.READER_TABLES, Oct 10 2026): every test runs the same way, each with its own readers' database, so a
    statement sent to the wrong database, or mixing the two, fails here."""
    monkeypatch.setenv("READERS_DATABASE_URL", f"sqlite:///{tmp_path / 'readers.db'}")


@pytest.fixture(autouse=True)
def model_verdicts_on(monkeypatch):
    """Red verdicts are on hold in production (SETTINGS.model_verdicts = False); the tests keep the
    machinery working for when a second model family is available."""
    import nishpaksh.run as run_mod
    monkeypatch.setattr(run_mod, "SETTINGS", dataclasses.replace(run_mod.SETTINGS, model_verdicts=True))


@pytest.fixture(autouse=True)
def no_settle_wait(monkeypatch, request):
    """Articles are written once coverage has settled (3 quiet hours). Tests run on articles fetched
    seconds ago, so the wait is off unless a test is about it (marked `settle`). No archive reads."""
    monkeypatch.setenv("NISHPAKSH_ARCHIVE_URL", "")
    if request.node.get_closest_marker("settle"):
        return
    import nishpaksh.editions as ed
    monkeypatch.setattr(ed, "SETTINGS", dataclasses.replace(ed.SETTINGS, settle_quiet_hours=0, read_wait_hours=0))


@pytest.fixture(autouse=True)
def pipeline_then_desk(monkeypatch):
    """In production the writing desk is its own job (desk.py); in tests a pipeline run is followed by
    the desk, so a run ends with what a reader would see."""
    import functools
    import nishpaksh.run as run_mod
    monkeypatch.setattr(run_mod, "run", functools.partial(run_mod.run, then_write=True))


@pytest.fixture(autouse=True)
def carry_over_off(monkeypatch, request):
    """Unused hourly allowances carry to later hours (carry.py, Oct 11 2026). Older tests are about one hour at a
    time, so carry-over is off unless a test is about it (marked `carry`)."""
    if request.node.get_closest_marker("carry"):
        return
    import nishpaksh.config as cfg
    monkeypatch.setattr(cfg, "SETTINGS", dataclasses.replace(cfg.SETTINGS, carry_over=False))


def fake_nli(pairs):
    """Stand-in for the local NLI model (nli.py): wording decides. A reads as entailing B when B's words are all in A
    (or the two share half their words with the same figures); the same wording with other figures or a negation
    flipped contradicts."""
    import re
    out = []
    for a, b in pairs:
        wa = {w for w in re.findall(r"[a-z]+", a.lower()) if len(w) > 2}
        wb = {w for w in re.findall(r"[a-z]+", b.lower()) if len(w) > 2}
        na, nb = set(re.findall(r"\d[\d,.]*", a)), set(re.findall(r"\d[\d,.]*", b))
        jac = len(wa & wb) / max(1, len(wa | wb))
        neg = ("not" in wa) != ("not" in wb)
        if jac >= 0.5 and (na != nb or neg):
            out.append((0.03, 0.07, 0.90))
        elif jac >= 0.5 and na == nb:
            out.append((0.95, 0.03, 0.02))
        elif wb and wb <= wa and nb <= na and not neg:
            out.append((0.92, 0.06, 0.02))
        else:
            out.append((0.08, 0.87, 0.05))
    return out


@pytest.fixture(autouse=True)
def local_nli(monkeypatch):
    """The NLI model is not downloaded in tests."""
    from nishpaksh import nli
    nli.set_backend(fake_nli)
    yield
    nli.set_backend(None)
