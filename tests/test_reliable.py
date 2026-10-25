from nishpaksh import reliable


def test_transient_failure_is_retried_then_succeeds():
    n = {"c": 0}

    def fn():
        n["c"] += 1
        if n["c"] < 3:
            raise reliable.HttpFailure(503)
        return "ok"
    out = reliable.call("t1", fn, attempts=3, sleep=lambda s: None)
    assert out.ok and out.value == "ok" and n["c"] == 3


def test_permanent_failure_is_not_retried_and_is_an_answer():
    n = {"c": 0}

    def fn():
        n["c"] += 1
        raise reliable.HttpFailure(404)
    out = reliable.call("t2", fn, attempts=3, sleep=lambda s: None)
    assert not out.ok and out.kind == reliable.PERMANENT and not out.could_not_ask and n["c"] == 1


def test_circuit_opens_after_repeated_transient_failures_and_closes_after_cooldown():
    def boom():
        raise TimeoutError("slow")
    name = "t3"
    for _ in range(2):
        reliable.call(name, boom, attempts=3, sleep=lambda s: None)
    out = reliable.call(name, boom, attempts=3, sleep=lambda s: None)
    assert out.kind == reliable.OPEN and out.could_not_ask
    b = reliable.breaker(name)
    assert b.allow(now=b.opened_at + b.cooldown + 1)


def test_backoff_is_jittered_and_capped():
    waits = []
    reliable.call("t4", lambda: (_ for _ in ()).throw(TimeoutError()), attempts=4, base=1, cap=2, sleep=waits.append)
    assert len(waits) == 3 and all(0 <= w <= 2 for w in waits)
