# Summary

<!-- What does this change, and why? For a defect, describe the incorrect
     behaviour rather than only the code that was edited. -->

## What was measured

<!-- CorpusSLR's claims are quantitative, so a change to behaviour is reviewable
     only alongside its effect. Delete the rows that do not apply.

     For deduplication changes, run both validation protocols and report before
     and after:
       python validation/eval_asysd.py
       python validation/eval_multidomain.py
-->

| Measurement | Before | After |
|---|---|---|
| Deduplication F1 (ASySD Diabetes, clustering) | | |
| False positives / false negatives | | |
| Multi-domain F1 (per arm, if affected) | | |
| Cost per record at 60 000 records | | |
| Tests | | |
| Coverage | | |

## Checklist

- [ ] `python -m pytest tests` passes on my default interpreter
- [ ] `python -m pytest tests` passes on **Python 3.9** (`requires-python = ">=3.9"`)
- [ ] `python -m ruff check .` reports nothing
- [ ] `python -m mypy corpusslr` reports nothing
- [ ] No test touches the network; new HTTP behaviour is exercised through the
      doubles in `tests/conftest.py`
- [ ] New behaviour has a test; a repaired defect has a regression test
- [ ] New public symbols are exported in `corpusslr/__init__.py` (appended, with
      `# noqa: F401`)
- [ ] Public docstrings state the methodological justification, in English
- [ ] `CHANGELOG.md` records the change under `[Unreleased]`
- [ ] Every figure added to documentation traces to a file under `validation/`

## Methodological consequences

<!-- Does this change what a review built with CorpusSLR would report — the
     number of records identified, which duplicates are removed, what the
     PRISMA-S appendix claims about reproducibility? If a new limitation arises,
     confirm it reaches SearchEvent.notes so it also reaches the appendix. -->
