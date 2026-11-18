"""corpusslr.notebook: the glue the Colab notebook calls, tested offline."""
import json
import os

import pytest

from corpusslr import notebook as nb

BLOCKS = [["artificial intelligence", "machine learning"], ["adoption"]]


def test_make_config_writes_a_validated_file_without_credentials(tmp_path, capsys):
    out = str(tmp_path / "review")
    config, path = nb.make_config(BLOCKS, ["crossref", "PubMed"], years=(2018, 2024),
                                  doc_types=["Article"], out_dir=out)
    assert os.path.isfile(path)
    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["query"]["blocks"] == [list(b) for b in BLOCKS]
    assert saved["query"]["years"] == [2018, 2024]
    assert saved["query"]["doc_types"] == ["article"]
    assert [d["name"] for d in saved["databases"]] == ["crossref", "pubmed"]
    text = json.dumps(saved)
    for name in ("SCOPUS", "WOS_API", "insttoken", "api_key", "apikey", "token"):
        assert name.lower() not in text.lower(), name


@pytest.mark.parametrize("blocks, databases, why", [
    ([], ["crossref"], "no terms"),
    ([["a", "machine learning"]], ["crossref"], "one-character term"),
    ([["machine learning"]], ["no_such_database"], "unknown database"),
    ([["machine learning"]], [], "no database"),
])
def test_make_config_refuses_a_query_that_cannot_work(tmp_path, blocks, databases, why):
    with pytest.raises(ValueError):
        nb.make_config(blocks, databases, out_dir=str(tmp_path / "x"))


def test_a_database_is_listed_once_however_it_is_spelled(tmp_path):
    config, _ = nb.make_config(BLOCKS, ["crossref", "Crossref", "crossref"],
                               out_dir=str(tmp_path / "x"))
    assert [d["name"] for d in config["databases"]] == ["crossref"]


def test_show_queries_prints_each_databases_own_syntax(tmp_path, capsys):
    config, _ = nb.make_config(BLOCKS, ["pubmed", "crossref"], out_dir=str(tmp_path / "x"))
    compiled = nb.show_queries(config)
    out = capsys.readouterr().out
    assert set(compiled) == {"pubmed", "crossref"}
    assert "machine learning" in compiled["pubmed"]
    assert "PubMed" in out


def test_read_summary_reports_a_missing_run_without_raising(tmp_path, capsys):
    assert nb.read_summary(str(tmp_path)) == {}
    assert "No run summary" in capsys.readouterr().out


def test_read_summary_prints_the_counts(tmp_path, capsys):
    (tmp_path / "run_summary.json").write_text(json.dumps({
        "identified": 10, "identified_by_source": {"crossref": 6, "pubmed": 4},
        "dedup": {"removed": 3, "after": 7, "by_method": {"doi": 2, "fuzzy_title": 1}},
        "failures": [{"database": "scopus", "reason": "no key"}]}))
    summary = nb.read_summary(str(tmp_path))
    out = capsys.readouterr().out
    assert summary["identified"] == 10
    assert "unique records     : 7" in out and "not searched: scopus" in out


def test_write_scopus_csv_needs_a_finished_run(tmp_path):
    with pytest.raises(FileNotFoundError):
        nb.write_scopus_csv(str(tmp_path))


def test_show_appendix_returns_the_text(tmp_path, capsys):
    assert nb.show_appendix(str(tmp_path)) == ""
    (tmp_path / "prisma_s_appendix.md").write_text("# appendix\n", encoding="utf-8")
    assert nb.show_appendix(str(tmp_path)).startswith("# appendix")


def test_download_results_zips_the_folder_and_degrades_outside_colab(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.txt").write_text("x")
    monkeypatch.chdir(tmp_path)
    archive = nb.download_results(str(out))
    assert os.path.isfile(archive) and archive.endswith(".zip")
    assert "Not running in Colab" in capsys.readouterr().out


def test_run_review_reports_a_failed_run_in_words(monkeypatch, capsys):
    monkeypatch.setattr(nb, "_cli_main", lambda argv: 2)
    assert nb.run_review("review.json", "out") == 2
    assert "stopped with code 2" in capsys.readouterr().out


def test_the_module_reads_no_credential():
    import inspect
    src = inspect.getsource(nb)
    assert "getpass" not in src.replace("``getpass``", "")
    assert "os.environ" not in src
