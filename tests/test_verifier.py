from pathlib import Path

from jarvis.verifier import VerifierResult, run_verifier


def vr(out: str, ok: bool = False) -> VerifierResult:
    return VerifierResult(ok, 0 if ok else 1, out, 1.0, "pytest")


def test_counts_pytest_jest_unittest():
    assert vr("==== 2 failed, 5 passed in 0.31s ====").counts() == (5, 2)
    assert vr("1 passed, 1 error in 0.1s").counts() == (1, 1)
    assert vr("Tests: 3 failing, 7 passing").counts() == (7, 3)
    assert vr("Ran 4 tests in 0.01s\n\nFAILED (failures=1, errors=1)").counts() == (2, 2)
    assert vr("todo raro").counts() is None


def test_not_worse_than():
    base = vr("2 failed, 3 passed")
    assert vr("2 failed, 3 passed").not_worse_than(base)
    assert vr("1 failed, 4 passed").not_worse_than(base)
    assert not vr("3 failed, 2 passed").not_worse_than(base)
    assert not vr("1 error").not_worse_than(base)
    assert vr("", ok=True).not_worse_than(base)
    assert not vr("2 failed, 3 passed").not_worse_than(vr("5 passed", ok=True))
    assert not vr("sin cuentas").not_worse_than(vr("sin cuentas tampoco"))


def test_signature_ignores_numbers():
    a = vr("FAILED test_x - assert 3 == 6\n1 failed in 0.12s")
    b = vr("FAILED test_x - assert 3 == 6\n1 failed in 0.98s")
    assert a.signature == b.signature


def test_run_verifier_exit_codes(tmp_path: Path):
    assert run_verifier("exit 0", tmp_path).ok
    r = run_verifier("exit 3", tmp_path)
    assert not r.ok and r.exit_code == 3
