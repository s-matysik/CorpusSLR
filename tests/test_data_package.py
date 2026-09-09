"""The validation-data upload is a build product, so it is testable.

What matters to a reader is that a filename they follow from the article or
the supplement is actually in the package, and that the checksums describe
what is there. Both are checked by reading the built package back.
"""
from __future__ import annotations

import csv
import hashlib
import os
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import corpusslr                                             # noqa: E402

bdp = pytest.importorskip("tools.build_data_package",
                          reason="tools/ is not present in this checkout")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("datapkg"))
    return bdp.build(out, write_zip=True, quiet=True)


def test_no_inventory_entry_is_missing(built):
    """A named file that is not in the repository would be listed in the
    README and absent from the download."""
    assert built["missing"] == [], built["missing"]


def test_every_cited_data_file_is_packaged_or_explained(built):
    """The check that matters: a filename in the documents must resolve.

    Anything the article or supplement names must either be in the package or
    carry a recorded reason for its absence. Silence is the failure mode.
    """
    assert built["uncovered"] == {}, (
        "cited but neither packaged nor listed as a deliberate omission: %s"
        % built["uncovered"])


def test_the_coverage_check_is_not_vacuous():
    """Prove the rule fires, rather than trusting that it would."""
    cited = bdp.cited_validation_files()
    assert cited, "no citations detected at all, so the rule proves nothing"
    packaged = {os.path.basename(rel) for rel, _s, _w in bdp.INVENTORY}
    # At least one real citation has to be resolved through the inventory,
    # otherwise the rule passes only because nothing is ever cited.
    assert packaged & set(cited), sorted(cited)[:5]


def test_the_manifest_checksums_match_the_files(built):
    with open(os.path.join(built["root"], "MANIFEST.csv"),
              encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == built["files"]
    for row in rows:
        full = os.path.join(built["root"], row["path"])
        assert os.path.exists(full), row["path"]
        h = hashlib.sha256()
        with open(full, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        assert h.hexdigest() == row["sha256"], row["path"]
        assert int(row["bytes"]) == os.path.getsize(full), row["path"]


def test_every_file_declares_what_it_supports(built):
    with open(os.path.join(built["root"], "MANIFEST.csv"),
              encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        assert len(row["supports"].split()) >= 4, (
            "%s has no usable description: %r" % (row["path"], row["supports"]))


def test_the_readme_names_the_current_version_and_the_licence(built):
    with open(os.path.join(built["root"], "README.md"), encoding="utf-8") as fh:
        text = fh.read()
    assert corpusslr.__version__ in text
    # The gold standard is redistributed, so its provenance has to travel with
    # it rather than being implied.
    assert "CC BY 4.0" in text and "Hair" in text
    assert "MIT" in text


def test_the_raw_records_are_included_so_the_evaluation_is_offline(built):
    names = {os.path.basename(rel) for rel, _s, _w in bdp.INVENTORY}
    for track in ("social", "stem", "nature_hum"):
        assert "domains_%s_raw.jsonl.gz" % track in names, track


def test_two_builds_of_the_same_inputs_are_byte_identical(tmp_path):
    """A submitted archive that differs between builds cannot be checked."""
    a = bdp.build(str(tmp_path / "a"), write_zip=True, quiet=True)
    b = bdp.build(str(tmp_path / "b"), write_zip=True, quiet=True)
    with open(a["zip"], "rb") as fh:
        first = fh.read()
    with open(b["zip"], "rb") as fh:
        second = fh.read()
    assert first == second, "the archive is not reproducible"


def test_the_zip_members_are_all_under_one_top_level_directory(built):
    with zipfile.ZipFile(built["zip"]) as zf:
        tops = {n.split("/")[0] for n in zf.namelist()}
    assert tops == {bdp.PKG_DIRNAME}, tops
