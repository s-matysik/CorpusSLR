"""Guided terminal interface: driven entirely from a substituted stdin.

Every test here is offline and terminal-free. The interface takes its streams
and its password reader by injection, which is what makes two things testable
that matter more than the happy path:

*   that a typed API key appears in **no** byte the interface ever writes, and
*   that a reviewer who types something wrong gets a sentence telling them
    what to do, never a Python exception.

Several tests are paired with a deliberately broken variant (``_leaky``,
``_raises``) that must make the assertion fail. A check that only ever sees
correct behaviour does not demonstrate that it can detect the defect it exists
to catch.
"""
import io
import json
import os
import stat

import pytest

from corpusslr import tui
from corpusslr.cli import DATABASES

SECRET = "sk-test-DO-NOT-LEAK-31415926"


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def private_config_home(tmp_path, monkeypatch):
    """Point credential storage at a temporary directory.

    Without this every test would read and write the developer's real
    ``~/.config/corpusslr/credentials.json``.
    """
    home = tmp_path / "config"
    monkeypatch.setenv("CORPUSSLR_CONFIG_HOME", str(home))
    return home


@pytest.fixture(autouse=True)
def no_inherited_credentials(monkeypatch):
    """Unset every credential variable so results do not depend on the host."""
    for slot in tui.credential_slots():
        monkeypatch.delenv(str(slot["variable"]), raising=False)


def flat(text):
    """Collapse all whitespace, so an assertion is insensitive to wrapping.

    The interface wraps every paragraph to 78 columns on purpose, which means
    a sentence a test looks for is routinely split across two lines. Asserting
    on the wrapped bytes would make the tests fail whenever a message is
    reworded by one word, without any behaviour having changed.
    """
    return " ".join(text.split())


def drive(keys, secrets=(), runner=None, getpass_fn=None):
    """Run the interface against a scripted stdin, returning its whole output.

    *keys* is the list of lines the reviewer types; a trailing ``"0"`` quits.
    """
    script = "\n".join(list(keys)) + "\n"
    out = io.StringIO()
    pending = list(secrets)

    def reader(prompt=""):
        return pending.pop(0) if pending else ""

    code = tui.main(stdin=io.StringIO(script), stdout=out,
                    getpass_fn=getpass_fn or reader,
                    runner=runner if runner is not None else _no_run)
    return code, out.getvalue()


def _no_run(argv, out):
    raise AssertionError("the runner must not be called by this test")


def _make_interface(keys, secrets=(), runner=None):
    script = "\n".join(list(keys)) + "\n"
    out = io.StringIO()
    pending = list(secrets)
    interface = tui.Interface(
        stdin=io.StringIO(script), stdout=out,
        getpass_fn=lambda prompt="": pending.pop(0) if pending else "",
        runner=runner)
    return interface, out


# ---------------------------------------------------------------------------
# the interface starts and stops
# ---------------------------------------------------------------------------
def test_quit_immediately_is_a_clean_exit():
    code, text = drive(["0"])
    assert code == 0
    assert "CorpusSLR" in flat(text)


def test_end_of_input_is_not_a_crash():
    """A closed stdin (piped, or Ctrl-D) must end the session, not raise."""
    out = io.StringIO()
    code = tui.main(stdin=io.StringIO(""), stdout=out, runner=_no_run)
    assert code == 0
    assert "Nothing was sent anywhere" in flat(out.getvalue())


def test_extra_arguments_are_explained_not_fatal():
    out = io.StringIO()
    code = tui.main(argv=["--config", "x.json"], stdin=io.StringIO(""),
                    stdout=out, runner=_no_run)
    assert code == 0
    assert "takes no arguments" in flat(out.getvalue())


def test_every_line_fits_eighty_columns():
    """A narrow terminal must not soft-wrap the interface's own output."""
    _code, text = drive(["1", "free", "2", "ai, ml", "", "", "", "",
                         "9", "", "0"])
    too_wide = [line for line in text.split("\n") if len(line) > 80]
    assert not too_wide, too_wide[:3]


def test_no_ansi_escape_sequences_anywhere():
    """No colour: some terminals and every screen reader render it as noise."""
    _code, text = drive(["1", "free", "9", "", "0"])
    # the probe can see an escape byte at all, so a clean result means absence
    assert "\x1b" in "before\x1b[31mafter"
    assert "\x1b" not in text
    assert "\x1b[" not in text


# ---------------------------------------------------------------------------
# database selection
# ---------------------------------------------------------------------------
def test_multiple_databases_by_number():
    aliases = sorted(DATABASES)
    interface, _out = _make_interface(["1,3", "0"])
    interface.credentials = {}
    picked = interface._parse_database_answer("1,3", aliases)
    assert picked == [aliases[0], aliases[2]]


def test_multiple_databases_selected_through_the_menu():
    aliases = sorted(DATABASES)
    _code, text = drive(["1", "1,3,5", "0"])
    expected = ", ".join(str(DATABASES[aliases[i]]["label"])
                         for i in (0, 2, 4))
    assert "Selected: " + expected in flat(text)


def test_word_free_selects_every_keyless_database():
    _code, text = drive(["1", "free", "0"])
    keyless = [a for a in sorted(DATABASES) if DATABASES[a]["keyless"]]
    expected = ", ".join(str(DATABASES[a]["label"]) for a in keyless)
    assert "Databases : " + expected in flat(text)


def test_institutional_spellings_are_accepted():
    """Reviewers write their library's name for a database, not our alias."""
    _code, text = drive(["1", "Web of Science, MEDLINE", "0"])
    assert "Web of Science Core Collection" in flat(text)
    assert "PubMed/MEDLINE" in flat(text)


def test_unknown_database_is_rejected_with_a_remedy():
    """The message must say what to type instead, and change nothing."""
    _code, text = drive(["1", "free", "1", "Embase", "0"])
    assert "I do not know a database called" in flat(text)
    assert "embase" in flat(text).lower()
    assert "Nothing was changed" in flat(text)
    # the remedy names the actual route for a database without an open API
    assert "menu item 4" in flat(text)
    # and the earlier selection survived the rejection
    keyless = [a for a in sorted(DATABASES) if DATABASES[a]["keyless"]]
    assert str(DATABASES[keyless[0]]["label"]) in flat(text)


def test_out_of_range_database_number_is_rejected():
    _code, text = drive(["1", "99", "0"])
    assert "no database number 99" in flat(text)
    assert "Nothing was changed" in flat(text)


def test_selecting_a_subscription_database_warns_about_the_missing_key():
    aliases = sorted(DATABASES)
    index = aliases.index("scopus") + 1
    _code, text = drive(["1", str(index), "0"])
    assert "need an API key that is not set yet" in flat(text)
    assert "menu item 3" in flat(text)


def test_none_clears_the_selection():
    _code, text = drive(["1", "free", "1", "none", "0"])
    assert "Selection cleared." in flat(text)


def test_unrecognised_menu_item_explains_itself():
    _code, text = drive(["banana", "0"])
    assert "I did not recognise 'banana'" in flat(text)
    assert "0 to quit" in flat(text)


# ---------------------------------------------------------------------------
# the query
# ---------------------------------------------------------------------------
def test_query_blocks_are_collected():
    _code, text = drive(
        ["2", "artificial intelligence, machine learning", "adoption",
         "", "2015-2026", "article", "en", "0"])
    assert "2 blocks, 3 terms, 2015-2026" in flat(text)


def test_one_character_term_is_refused_with_a_reason():
    _code, text = drive(["2", "a, machine learning", "adoption", "",
                         "", "", "", "0"])
    assert "too short to be a search term" in flat(text)
    assert "Retype this block" in flat(text)


def test_unreadable_year_range_does_not_stop_the_session():
    _code, text = drive(["2", "machine learning", "", "last decade",
                         "", "", "0"])
    assert "could not read 'last decade' as a year range" in flat(text)
    assert "2015-2026" in text            # the message shows the right shape


def test_reversed_years_are_swapped_and_reported():
    _code, text = drive(["2", "machine learning", "", "2026-2015",
                         "", "", "0"])
    assert "Swapped the years so the range reads 2015-2026" in flat(text)


def test_implausible_years_are_refused():
    _code, text = drive(["2", "machine learning", "", "15-26",
                         "", "", "0"])
    assert "outside the plausible range" in flat(text)


def test_empty_query_leaves_the_previous_one_untouched():
    _code, text = drive(["2", "machine learning", "", "", "", "",
                         "2", "", "0"])
    assert "No blocks entered; the query is unchanged." in flat(text)
    assert "1 block, 1 term" in flat(text)


# ---------------------------------------------------------------------------
# credentials: storage, permissions, and never being echoed
# ---------------------------------------------------------------------------
def _scopus_slot_number():
    slots = tui.credential_slots()
    for i, slot in enumerate(slots, 1):
        if slot["variable"] == "SCOPUS_API_KEY":
            return str(i)
    raise AssertionError("SCOPUS_API_KEY is not offered by the interface")


def test_api_key_never_appears_in_any_output():
    """The load-bearing security test: the whole transcript is searched.

    Everything the interface writes goes through one stream, so a single
    substring check over the accumulated output covers the menu, the status
    line, the plan, the confirmation and every error message.
    """
    slot = _scopus_slot_number()
    _code, text = drive(["3", slot, "3", "1", "free", "6", "0"],
                        secrets=[SECRET])
    assert SECRET not in text
    assert SECRET[:10] not in text            # not even a prefix
    assert tui.MASK in text                   # presence is reported instead
    assert "SCOPUS_API_KEY" in text           # by variable name only


def test_the_leak_check_detects_a_deliberately_leaky_interface():
    """Fault injection: prove the assertion above can fail.

    A check that has only ever seen correct behaviour does not demonstrate
    that it detects the defect it exists to catch. This subclass echoes the
    stored credential the way a careless status line would, and the same
    assertion must reject it.
    """
    class _Leaky(tui.Interface):
        def _credential_line(self):
            return ", ".join("{}={}".format(k, v)
                             for k, v in self.credentials.items())

    slot = _scopus_slot_number()
    script = "\n".join(["3", slot, "0"]) + "\n"
    out = io.StringIO()
    pending = [SECRET]
    interface = _Leaky(stdin=io.StringIO(script), stdout=out,
                       getpass_fn=lambda prompt="": pending.pop(0),
                       runner=_no_run)
    interface.run()
    leaked = out.getvalue()
    assert SECRET in leaked, "the injected leak did not occur"
    with pytest.raises(AssertionError):
        assert SECRET not in leaked


def test_stored_credential_is_owner_readable_only():
    slot = _scopus_slot_number()
    drive(["3", slot, "0"], secrets=[SECRET])
    path = tui.credentials_path()
    assert os.path.isfile(path)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, oct(mode)
    assert not mode & 0o077


def test_group_and_world_bits_are_repaired_on_startup():
    """A file left readable by others is tightened, and the user is told."""
    slot = _scopus_slot_number()
    drive(["3", slot, "0"], secrets=[SECRET])
    path = tui.credentials_path()
    os.chmod(path, 0o644)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o644
    _code, text = drive(["0"])
    assert "tightened to owner-only" in flat(text)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_the_permission_check_detects_a_loose_file():
    """Fault injection for the 0600 assertion itself."""
    tui.save_credentials({"SCOPUS_API_KEY": SECRET})
    path = tui.credentials_path()
    os.chmod(path, 0o666)
    with pytest.raises(AssertionError):
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_stored_credential_round_trips():
    slot = _scopus_slot_number()
    drive(["3", slot, "0"], secrets=[SECRET])
    assert tui.load_credentials()["SCOPUS_API_KEY"] == SECRET


def test_empty_key_does_not_crash_and_deletes_nothing():
    """Pressing Enter at the key prompt is a normal outcome."""
    slot = _scopus_slot_number()
    tui.save_credentials({"SCOPUS_API_KEY": SECRET})
    code, text = drive(["3", slot, "0"], secrets=[""])
    assert code == 0
    assert "Nothing entered" in flat(text)
    assert "nothing broke" in flat(text)
    assert tui.load_credentials()["SCOPUS_API_KEY"] == SECRET


def test_non_numeric_key_choice_is_explained():
    _code, text = drive(["3", "scopus", "0"])
    assert "Type one of the numbers shown" in flat(text)


def test_key_prompt_can_be_left_by_pressing_enter():
    _code, text = drive(["3", "", "0"])
    assert "Choose an item" in flat(text)


def test_contact_address_is_not_read_through_getpass():
    """The politeness address is not a secret, so it is typed visibly."""
    slots = tui.credential_slots()
    number = str(len(slots))
    assert slots[-1]["variable"] == "CORPUSSLR_CONTACT_EMAIL"
    assert not slots[-1]["secret"]
    _code, _text = drive(["3", number, "reviewer@example.org", "0"])
    assert tui.load_credentials()["CORPUSSLR_CONTACT_EMAIL"] == \
        "reviewer@example.org"


def test_corrupt_credentials_file_is_treated_as_empty(private_config_home):
    private_config_home.mkdir(parents=True, exist_ok=True)
    (private_config_home / "credentials.json").write_text(
        "{not json", encoding="utf-8")
    assert tui.load_credentials() == {}
    code, _text = drive(["0"])
    assert code == 0


def test_absent_credentials_file_reports_no_mode():
    assert tui.credentials_mode() == -1


def test_credential_slots_match_what_the_cli_reads():
    """The interface must not store a key under a name the CLI ignores."""
    from corpusslr.cli import CREDENTIAL_ENV
    known = set()
    for spec in CREDENTIAL_ENV.values():
        known.update(spec["required"])
        known.update(spec["optional"])
    from corpusslr.cli import CONTACT_ENV
    known.update(CONTACT_ENV)
    for slot in tui.credential_slots():
        assert slot["variable"] in known, slot


def test_environment_patch_restores_the_previous_value(monkeypatch):
    monkeypatch.setenv("SCOPUS_API_KEY", "original")
    with tui._EnvironmentPatch({"SCOPUS_API_KEY": SECRET}):
        assert os.environ["SCOPUS_API_KEY"] == SECRET
    assert os.environ["SCOPUS_API_KEY"] == "original"


def test_environment_patch_removes_a_variable_it_introduced(monkeypatch):
    monkeypatch.delenv("WOS_API_KEY", raising=False)
    with tui._EnvironmentPatch({"WOS_API_KEY": SECRET}):
        assert os.environ["WOS_API_KEY"] == SECRET
    assert "WOS_API_KEY" not in os.environ


def test_environment_patch_does_not_swallow_an_exception():
    with pytest.raises(ValueError), \
            tui._EnvironmentPatch({"WOS_API_KEY": SECRET}):
        raise ValueError("must propagate")


# ---------------------------------------------------------------------------
# the plan
# ---------------------------------------------------------------------------
def test_check_refuses_until_there_is_a_query():
    _code, text = drive(["6", "0"])
    assert "the search query is empty" in flat(text)


def test_check_refuses_until_a_source_is_chosen():
    _code, text = drive(["2", "machine learning", "", "", "", "",
                         "6", "0"])
    assert "no database and no exported file is selected" in flat(text)


def test_check_shows_the_compiled_query_and_retrieves_nothing():
    _code, text = drive(["1", "free", "2", "machine learning", "adoption",
                         "", "2015-2026", "", "", "6", "0"])
    assert "Nothing has been retrieved." in flat(text)
    assert "PRISMA-S" in flat(text)
    assert "machine learning" in flat(text)


def test_check_reports_a_missing_key_as_a_skip():
    aliases = sorted(DATABASES)
    index = str(aliases.index("scopus") + 1)
    _code, text = drive(["1", index, "2", "machine learning", "",
                         "", "", "", "6", "0"])
    assert "MISSING -- this database would be skipped" in flat(text)


def test_a_stored_key_makes_the_plan_report_it_present():
    aliases = sorted(DATABASES)
    index = str(aliases.index("scopus") + 1)
    slot = _scopus_slot_number()
    _code, text = drive(["3", slot, "1", index, "2", "machine learning",
                         "", "", "", "", "6", "0"], secrets=[SECRET])
    assert "key: present" in flat(text)
    assert SECRET not in text


def test_compiled_query_is_never_truncated_at_the_margin():
    """A cut-off search string is a query that does not run.

    ``verbatim`` therefore wraps only at spaces and never trims, unlike the
    fixed-width table rows.
    """
    interface, out = _make_interface(["0"])
    term = "supercalifragilistic" * 6            # one unbreakable long token
    interface.verbatim(term)
    assert term in out.getvalue()


def test_table_rows_are_clipped_but_verbatim_lines_are_not():
    interface, out = _make_interface(["0"])
    interface.raw("x" * 200)
    first = out.getvalue().strip()
    assert len(first) == tui.WIDTH


# ---------------------------------------------------------------------------
# file exports
# ---------------------------------------------------------------------------
def test_missing_export_file_is_reported_without_a_traceback(tmp_path):
    ghost = str(tmp_path / "nope.ris")
    _code, text = drive(["4", ghost, "0"])
    assert "There is no readable file at" in flat(text)
    assert "Nothing was added." in flat(text)
    assert "Traceback" not in text


def test_export_file_is_added_with_its_provenance(tmp_path):
    export = tmp_path / "embase.ris"
    export.write_text("TY  - JOUR\nTI  - A title\nER  - \n", encoding="utf-8")
    _code, text = drive(["4", str(export), "Embase", "'ai' AND 'adoption'",
                         "0"])
    assert "1 file" in flat(text)
    assert "queued for import" in flat(text)


def test_a_file_alone_is_enough_to_be_ready_to_run(tmp_path):
    export = tmp_path / "embase.ris"
    export.write_text("TY  - JOUR\nTI  - A title\nER  - \n", encoding="utf-8")
    _code, text = drive(["2", "machine learning", "", "", "", "",
                         "4", str(export), "Embase", "",
                         "6", "0"])
    assert "no database and no exported file is selected" not in flat(text)


# ---------------------------------------------------------------------------
# output settings
# ---------------------------------------------------------------------------
def test_output_folder_and_cap_are_accepted(tmp_path):
    target = str(tmp_path / "results")
    _code, text = drive(["5", target, "500", "n", "0"])
    assert "Results will be written to {}".format(target) in flat(text)
    assert "Output folder : {}".format(target) in flat(text)
    assert "500" in flat(text)


def test_a_nonsense_record_limit_keeps_the_old_value():
    _code, text = drive(["5", "", "many", "y", "0"])
    assert "is not a whole number above zero" in flat(text)
    assert "stays at 2000" in flat(text)


def test_a_zero_record_limit_is_refused():
    _code, text = drive(["5", "", "0", "y", "0"])
    assert "stays at 2000" in flat(text)


# ---------------------------------------------------------------------------
# saving and loading settings
# ---------------------------------------------------------------------------
def test_settings_round_trip_through_a_file(tmp_path):
    path = str(tmp_path / "saved.json")
    _code, _text = drive(["1", "free", "2", "machine learning, deep learning",
                          "adoption", "", "2015-2026", "article", "",
                          "8", "1", path, "0"])
    assert os.path.isfile(path)
    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["query"]["blocks"] == [["machine learning", "deep learning"],
                                        ["adoption"]]
    _code, text = drive(["8", "2", path, "0"])
    assert "2 blocks, 3 terms, 2015-2026" in text


def test_a_saved_settings_file_contains_no_credential(tmp_path):
    path = str(tmp_path / "saved.json")
    slot = _scopus_slot_number()
    drive(["3", slot, "1", "free", "2", "machine learning", "",
           "", "", "", "8", "1", path, "0"], secrets=[SECRET])
    body = open(path, encoding="utf-8").read()
    assert SECRET not in body
    for name in ("api_key", "insttoken", "SCOPUS_API_KEY"):
        assert name not in body


def test_loading_malformed_json_explains_the_likely_cause(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"query": {"blocks": [["ai"]],}', encoding="utf-8")
    _code, text = drive(["8", "2", str(path), "0"])
    assert "is not valid JSON" in flat(text)
    assert "missing comma or quote" in flat(text)


def test_loading_an_invalid_configuration_is_reported_as_a_sentence(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"query": {"blocks": []},
                                "databases": ["openalex"]}),
                    encoding="utf-8")
    _code, text = drive(["8", "2", str(path), "0"])
    assert "That will not work yet:" in flat(text)
    assert "Traceback" not in text


def test_loading_a_configuration_with_a_key_in_it_is_refused(tmp_path):
    """The CLI's own guard must reach the reviewer as plain advice."""
    path = tmp_path / "leaky.json"
    path.write_text(json.dumps({"query": {"blocks": [["ai"]]},
                                "databases": ["openalex"],
                                "api_key": SECRET}), encoding="utf-8")
    _code, text = drive(["8", "2", str(path), "0"])
    assert "environment variables only" in flat(text)
    assert SECRET not in text


def test_loading_a_missing_settings_file_changes_nothing(tmp_path):
    _code, text = drive(["8", "2", str(tmp_path / "absent.json"), "0"])
    assert "Nothing was loaded." in flat(text)


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------
def test_run_refuses_before_the_answers_are_complete():
    _code, text = drive(["7", "0"])
    assert "Not ready to run yet:" in flat(text)


def test_run_writes_a_depositable_configuration_then_calls_the_pipeline(
        tmp_path):
    """The configuration is written *before* retrieval and holds no key."""
    out_dir = str(tmp_path / "review")
    seen = {}

    def runner(argv, out):
        seen["argv"] = list(argv)
        seen["scopus_in_env"] = os.environ.get("SCOPUS_API_KEY", "")
        return 0

    slot = _scopus_slot_number()
    _code, text = drive(["3", slot, "1", "free",
                         "2", "machine learning", "", "", "", "",
                         "5", out_dir, "", "n",
                         "7", "0"],
                        secrets=[SECRET], runner=runner)
    cfg_path = os.path.join(out_dir, "review.json")
    assert os.path.isfile(cfg_path)
    body = open(cfg_path, encoding="utf-8").read()
    assert SECRET not in body
    assert "corpusslr run -c {}".format(cfg_path) in flat(text)
    assert seen["argv"] == ["run", "-c", cfg_path, "-C", out_dir,
                            "--keep-going"]
    # the key was available to the pipeline, and only for its duration
    assert seen["scopus_in_env"] == SECRET
    assert "SCOPUS_API_KEY" not in os.environ
    assert SECRET not in text


def test_a_failed_run_is_explained_in_terms_of_what_to_do(tmp_path):
    out_dir = str(tmp_path / "review")
    _code, text = drive(["1", "free", "2", "machine learning", "",
                         "", "", "", "5", out_dir, "", "n",
                         "7", "", "0"],
                        runner=lambda argv, out: 2)
    assert "stopped with code 2" in flat(text)
    assert "missing API key" in flat(text)
    assert "Traceback" not in text


def test_run_writes_the_scopus_csv_and_lists_the_deliverables(tmp_path):
    """After a successful run the canonical export must exist on disk."""
    import csv

    from corpusslr import Corpus, Record
    from corpusslr.cli import write_corpus

    out_dir = tmp_path / "review"
    out_dir.mkdir()

    def runner(argv, out):
        corpus = Corpus()
        corpus.add_records([
            Record(title="Machine learning adoption in SMEs",
                   authors=["Doe, J."], year=2020, journal="J. Tests",
                   doi="10.1000/x", source="openalex"),
        ], database="OpenAlex")
        write_corpus(corpus, str(out_dir / "corpus_unique.json"))
        return 0

    _code, text = drive(["1", "free", "2", "machine learning", "",
                         "", "", "", "5", str(out_dir), "", "n",
                         "7", "0"], runner=runner)
    scopus_csv = out_dir / "corpus_scopus.csv"
    assert scopus_csv.is_file()
    rows = list(csv.reader(open(str(scopus_csv), newline="",
                                encoding="utf-8")))
    assert rows[0][:4] == ["Authors", "Author full names", "Author(s) ID",
                           "Title"]
    assert len(rows) == 2
    assert "corpus_scopus.csv" in flat(text)
    assert "screening.csv" in flat(text)
    assert "prisma_s_appendix.md" in flat(text)


def test_an_unreadable_corpus_after_a_run_is_reported_not_raised(tmp_path):
    out_dir = tmp_path / "review"
    out_dir.mkdir()

    def runner(argv, out):
        (out_dir / "corpus_unique.json").write_text("{ truncated",
                                                    encoding="utf-8")
        return 0

    _code, text = drive(["1", "free", "2", "machine learning", "",
                         "", "", "", "5", str(out_dir), "", "n",
                         "7", "0"], runner=runner)
    assert "could not reopen" in flat(text)
    assert "Traceback" not in text


def test_an_uncreatable_output_folder_is_explained(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    target = str(blocker / "inside")
    _code, text = drive(["1", "free", "2", "machine learning", "",
                         "", "", "", "5", target, "", "n",
                         "7", "0"])
    assert "cannot create the folder" in flat(text) or "refused that" in flat(text)
    assert "Traceback" not in text


# ---------------------------------------------------------------------------
# no Python exception ever reaches the reviewer
# ---------------------------------------------------------------------------
def test_an_internal_defect_is_reported_and_the_session_survives():
    """An unexpected exception is an interface defect, not a user error."""
    class _Raises(tui.Interface):
        def screen_databases(self):
            raise RuntimeError("injected defect")

    script = "\n".join(["1", "", "0"]) + "\n"
    out = io.StringIO()
    interface = _Raises(stdin=io.StringIO(script), stdout=out,
                        getpass_fn=lambda prompt="": "", runner=_no_run)
    code = interface.run()
    text = out.getvalue()
    assert code == 0                       # the session continued to the menu
    assert "RuntimeError: injected defect" in flat(text)
    assert "This is a defect, not your mistake" in flat(text)
    assert "github.com/s-matysik/CorpusSLR/issues" in flat(text)
    assert "Traceback (most recent call last)" not in text


def test_the_defect_guard_does_not_hide_a_normal_cancellation():
    """Ctrl-D inside a screen returns to the menu, not a defect report."""
    _code, text = drive(["1", "0"])          # stdin ends inside the screen
    assert "Cancelled that step" in flat(text) or "Leaving." in flat(text)
    assert "This is a defect" not in flat(text)


def test_help_screen_teaches_the_methodology():
    _code, text = drive(["9", "", "0"])
    for expected in ("Gusenbauer", "PRISMA-S", "bibliometrix", "VOSviewer",
                     "ASReview"):
        assert expected in flat(text), expected


def test_help_entries_are_all_prose():
    assert len(tui._HELP) >= 6
    for heading, body in tui._HELP:
        assert heading and body
        assert len(body) > 80, heading


# ---------------------------------------------------------------------------
# the CLI subcommand
# ---------------------------------------------------------------------------
def test_cli_exposes_a_tui_subcommand():
    from corpusslr.cli import build_parser
    args = build_parser().parse_args(["tui"])
    assert args.command == "tui"


def test_cli_tui_subcommand_starts_and_exits_cleanly():
    from corpusslr.cli import main as cli_main
    out, err = io.StringIO(), io.StringIO()
    code = cli_main(["tui"], stdout=out, stderr=err)
    assert code == 0
    # progress and prompts go to stderr, keeping stdout free for data
    assert "CorpusSLR" in flat(err.getvalue())


@pytest.mark.filterwarnings("ignore:.*found in sys.modules.*:RuntimeWarning")
def test_module_is_runnable_as_python_dash_m():
    """``python -m corpusslr.tui`` must be a real entry point.

    The RuntimeWarning is filtered because it is an artefact of re-running an
    already-imported module inside the test process, not a property of the
    entry point: a real ``python -m`` invocation starts with an empty
    ``sys.modules`` and never emits it.
    """
    import runpy
    import sys
    from unittest import mock
    with mock.patch.object(sys, "argv", ["corpusslr.tui"]), \
            mock.patch.object(sys, "stdin", io.StringIO("")), \
            mock.patch.object(sys, "stdout", io.StringIO()), \
            pytest.raises(SystemExit) as caught:
        runpy.run_module("corpusslr.tui", run_name="__main__")
    assert caught.value.code == 0


# ---------------------------------------------------------------------------
# the remaining branches of each helper
# ---------------------------------------------------------------------------
def test_config_home_honours_xdg_then_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("CORPUSSLR_CONFIG_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg-probe")
    assert tui.config_home() == os.path.join("/tmp/xdg-probe", "corpusslr")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    expected = os.path.join(os.path.expanduser("~"), ".config", "corpusslr")
    assert tui.config_home() == expected


def test_credentials_file_holding_a_list_is_treated_as_empty(
        private_config_home):
    private_config_home.mkdir(parents=True, exist_ok=True)
    (private_config_home / "credentials.json").write_text(
        '["not", "a", "mapping"]', encoding="utf-8")
    assert tui.load_credentials() == {}


def test_blank_stored_values_are_dropped(private_config_home):
    private_config_home.mkdir(parents=True, exist_ok=True)
    (private_config_home / "credentials.json").write_text(
        json.dumps({"SCOPUS_API_KEY": "   ", "WOS_API_KEY": "real"}),
        encoding="utf-8")
    assert tui.load_credentials() == {"WOS_API_KEY": "real"}


def test_credential_slots_offer_one_variable_per_kind():
    """Alternative spellings must not each become a separate menu entry."""
    variables = [s["variable"] for s in tui.credential_slots()]
    assert len(variables) == len(set(variables))
    assert "ELSEVIER_API_KEY" not in variables      # SCOPUS_API_KEY covers it


def test_languages_and_title_reach_the_configuration():
    settings = tui.ReviewSettings()
    settings.blocks = [["machine learning"]]
    settings.languages = ["en", "pl"]
    settings.doc_types = ["article"]
    settings.title = "A named review"
    cfg = settings.as_config()
    assert cfg["query"]["languages"] == ["en", "pl"]
    assert cfg["query"]["doc_types"] == ["article"]
    assert cfg["review"]["title"] == "A named review"


def test_a_blank_line_in_a_paragraph_is_preserved():
    interface, out = _make_interface(["0"])
    interface.say("first\n\nsecond")
    assert out.getvalue() == "first\n\nsecond\n"


def test_isatty_failure_is_treated_as_a_non_terminal():
    """A stream whose isatty() raises must not take the session down."""
    class _Hostile(io.StringIO):
        def isatty(self):
            raise OSError("no tty here")

    interface = tui.Interface(stdin=_Hostile("0\n"), stdout=io.StringIO(),
                              getpass_fn=lambda prompt="": "", runner=_no_run)
    assert interface._input_echoes() is False
    assert interface.run() == 0


def test_an_interactive_terminal_is_not_double_spaced():
    """When the terminal echoes, the interface must not add its own newline."""
    class _Tty(io.StringIO):
        def isatty(self):
            return True

    interface = tui.Interface(stdin=_Tty("0\n"), stdout=io.StringIO(),
                              getpass_fn=lambda prompt="": "", runner=_no_run)
    assert interface._input_echoes() is True


def test_a_getpass_reader_that_hits_end_of_input_leaves_the_screen():
    def reader(prompt=""):
        raise EOFError

    slot = _scopus_slot_number()
    script = "\n".join(["3", slot, "0"]) + "\n"
    out = io.StringIO()
    interface = tui.Interface(stdin=io.StringIO(script), stdout=out,
                              getpass_fn=reader, runner=_no_run)
    assert interface.run() == 0
    assert "Cancelled that step" in flat(out.getvalue())


def test_confirm_accepts_an_explicit_no():
    interface, _out = _make_interface(["n", "0"])
    assert interface.confirm("Really?", default=True) is False


def test_confirm_on_an_empty_answer_keeps_the_default():
    """Pressing Enter must accept the shown default, either way round."""
    interface, _out = _make_interface(["", "", "0"])
    assert interface.confirm("Recover abstracts?", default=True) is True
    assert interface.confirm("Recover abstracts?", default=False) is False


def test_a_variable_shared_by_two_databases_is_offered_once(monkeypatch):
    """A credential listed under two databases must not appear twice.

    Two menu entries writing the same environment variable would let a
    reviewer set a key under one heading and see it reported as absent under
    the other.
    """
    shared = {
        "scopus": {"required": ("SHARED_KEY",), "optional": ()},
        "wos": {"required": ("SHARED_KEY",), "optional": ()},
    }
    merged = dict(tui.CREDENTIAL_ENV)
    merged.update(shared)
    monkeypatch.setattr(tui, "CREDENTIAL_ENV", merged)
    variables = [s["variable"] for s in tui.credential_slots()]
    assert variables.count("SHARED_KEY") == 1
    assert len(variables) == len(set(variables))


def test_confirm_accepts_polish_true():
    """"tak" is the answer a Polish-speaking reviewer types for yes."""
    interface, _out = _make_interface(["tak", "0"])
    assert interface.confirm("Really?", default=False) is True


def test_the_word_all_selects_every_database():
    _code, text = drive(["1", "all", "0"])
    for alias in sorted(DATABASES):
        assert str(DATABASES[alias]["label"]) in flat(text)


def test_a_semicolon_separated_list_is_accepted():
    aliases = sorted(DATABASES)
    interface, _out = _make_interface(["0"])
    assert interface._parse_database_answer("1;3", aliases) == \
        [aliases[0], aliases[2]]


def test_an_empty_database_answer_changes_nothing():
    _code, text = drive(["1", "free", "1", "", "0"])
    assert "Nothing entered; the selection is unchanged." in flat(text)


def test_a_stray_separator_is_ignored_rather_than_rejected():
    aliases = sorted(DATABASES)
    interface, _out = _make_interface(["0"])
    assert interface._parse_database_answer("1,,3", aliases) == \
        [aliases[0], aliases[2]]


def test_an_answer_of_only_separators_is_reported():
    aliases = sorted(DATABASES)
    interface, out = _make_interface(["0"])
    assert interface._parse_database_answer(",,", aliases) is None
    assert "Nothing recognised" in flat(out.getvalue())


def test_a_query_line_of_only_commas_is_refused():
    _code, text = drive(["2", ",,,", "machine learning", "",
                         "", "", "", "0"])
    assert "That line had no terms in it" in flat(text)


def test_a_key_set_in_the_shell_is_reported_as_such(monkeypatch):
    monkeypatch.setenv("WOS_API_KEY", "from-the-shell")
    _code, text = drive(["3", "", "0"])
    assert "(set in your shell)" in flat(text)
    assert "from-the-shell" not in text


def test_an_empty_contact_address_changes_nothing():
    slots = tui.credential_slots()
    number = str(len(slots))
    _code, text = drive(["3", number, "", "0"])
    assert "is unchanged" in flat(text)
    assert tui.load_credentials() == {}


def test_already_added_files_are_listed_again(tmp_path):
    export = tmp_path / "embase.ris"
    export.write_text("TY  - JOUR\nTI  - T\nER  - \n", encoding="utf-8")
    _code, text = drive(["4", str(export), "Embase", "",
                         "4", "", "0"])
    # the label survives even when the path is longer than the terminal
    assert "Already added:" in flat(text)
    assert "1) Embase --" in flat(text)
    assert "embase.ris" in flat(text)


def test_pressing_enter_leaves_the_file_screen():
    _code, text = drive(["4", "", "0"])
    assert "Choose an item" in flat(text)


def test_pressing_enter_leaves_the_load_prompt():
    _code, text = drive(["8", "2", "", "0"])
    assert "Choose an item" in flat(text)


def test_pressing_enter_leaves_the_settings_screen():
    _code, text = drive(["8", "", "0"])
    assert "Choose an item" in flat(text)


def test_the_default_runner_calls_the_cli_and_hides_its_json(tmp_path):
    """The real runner must send progress to the terminal, JSON nowhere.

    ``corpusslr run`` writes a machine-readable summary to stdout for
    pipelines; printing a page of JSON at a guided reviewer is noise, so the
    interface sinks it and the same numbers are read back from
    ``run_summary.json``.
    """
    out = io.StringIO()
    code = tui._default_runner(["check", "-c", str(tmp_path / "absent.json")],
                               out)
    assert code != 0                       # the config does not exist
    assert out.getvalue()                  # the explanation reached the user
    assert "{" not in out.getvalue()       # ... and no JSON did


def test_the_json_sink_satisfies_the_stream_protocol():
    sink = tui._Sink()
    assert sink.write("ignored") == len("ignored")
    assert sink.flush() is None


def test_a_file_system_error_inside_a_screen_is_explained():
    """An OSError must reach the reviewer as advice, not as a defect."""
    class _Broken(tui.Interface):
        def screen_output(self):
            raise OSError("disk is full")

    script = "\n".join(["5", "", "0"]) + "\n"
    out = io.StringIO()
    interface = _Broken(stdin=io.StringIO(script), stdout=out,
                        getpass_fn=lambda prompt="": "", runner=_no_run)
    assert interface.run() == 0
    text = flat(out.getvalue())
    assert "The file system refused that: disk is full" in text
    assert "This is a defect" not in text


# ---------------------------------------------------------------------------
# no dependency beyond the standard library
# ---------------------------------------------------------------------------
def test_the_interface_imports_nothing_outside_the_standard_library():
    """The hard requirement: standard library plus CorpusSLR itself.

    Enforced by reading the module's own import statements rather than by
    inspecting a loaded namespace, so a lazily imported console library would
    still be caught.
    """
    import ast
    import sys
    source = open(tui.__file__, encoding="utf-8").read()
    tree = ast.parse(source)
    external = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                external.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:                  # relative: inside CorpusSLR
                continue
            external.add((node.module or "").split(".")[0])
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    banned = {"curses", "rich", "textual", "blessed", "prompt_toolkit",
              "click", "urwid", "colorama", "requests"}
    assert not (external & banned), external & banned
    if stdlib:                              # Python 3.10+
        assert external <= stdlib, external - stdlib


def test_the_dependency_check_would_catch_a_banned_import(tmp_path):
    """Fault injection for the check above."""
    import ast
    probe = "import curses\nimport rich\n"
    tree = ast.parse(probe)
    external = {alias.name.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names}
    banned = {"curses", "rich", "textual"}
    with pytest.raises(AssertionError):
        assert not (external & banned)
