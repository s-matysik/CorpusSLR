"""The query compiler is checked against hand-written reference queries.

The live comparison (hit counts of the compiled and the reference query on the
same database) cannot run in the offline suite and is recorded in
validation/query_compiler_validation.csv. What can run offline is checked here:
the syntax conditions, that the recorded file describes the compiler as it is
now, and that the syntax check itself is able to fail.
"""
import csv
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "validation"))
import validate_query_compiler as V  # noqa: E402


@pytest.mark.parametrize("case", V.CASES, ids=[c[0] for c in V.CASES])
def test_every_compiled_string_meets_the_syntax_conditions(case):
    cid, _desc, spec, _refs = case
    q = V.build(spec)
    for db, meth in V.COMPILERS.items():
        compiled = getattr(q, meth)()
        assert V.syntax_problems(db, compiled, spec) == [], (cid, db, compiled)


def test_the_recorded_validation_describes_the_current_compiler():
    with open(os.path.join(ROOT, "validation", "query_compiler_validation.csv"),
              encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 3 * len(V.CASES)
    by_case = {c[0]: c for c in V.CASES}
    for r in rows:
        spec = by_case[r["case"]][2]
        assert r["compiled"] == getattr(V.build(spec), V.COMPILERS[r["database"]])(), \
            "%s/%s: the compiler's output has changed since the validation was run" % (
                r["case"], r["database"])
        assert r["reference"] == by_case[r["case"]][3][r["database"]]
        assert r["syntax_problems"] == "none"


def test_live_agreement_is_recorded_only_where_it_was_measured():
    with open(os.path.join(ROOT, "validation", "query_compiler_validation.csv"),
              encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        if r["agreement"] == "equal":
            assert r["count_compiled"] == r["count_reference"] != ""
            assert int(r["count_compiled"]) > 0, "a zero-hit pair proves nothing"
        else:
            assert r["agreement"] == "not run", r
            assert r["count_compiled"] == ""


@pytest.mark.parametrize("broken, why", [
    ('TS=("machine learning" OR "deep learning"', "parentheses"),
    ('TS=("machine learning" OR "deep learning)', "quotation"),
    ('TS=("machine learning")', "phrase"),
    ('TS=("machine learning" OR "deep learning") AND AND PY=2015-2024', "operand"),
])
def test_negative_control_the_syntax_check_can_fail(broken, why):
    spec = {"blocks": [["machine learning", "deep learning"]], "years": (2015, 2024)}
    assert V.syntax_problems("wos", broken, spec), why
