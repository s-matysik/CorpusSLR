"""Guided terminal interface: a whole review without writing Python.

Why this module exists at all, given that :mod:`corpusslr.cli` is already a
complete non-programmer interface: a CLI still asks the reviewer to *author* a
JSON configuration file before anything happens.  That is a small step for a
developer and a hard stop for the people who most often own a search strategy
-- information specialists, librarians, domain experts.  The guided interface
inverts the order: it asks the questions, and the configuration file is what
comes *out*.  The file it writes is the same declarative artefact
``corpusslr run -c`` consumes, so a review started here can be rerun,
diffed and deposited exactly like one written by hand, and nothing about the
interface is a private code path.

Design constraints, all of them deliberate and all of them testable:

*Standard library only.*  ``input``, ``print``, ``getpass``, ``json``, ``os``.
No curses, no readline dependency, no third-party console library.  A review
is often run on a borrowed machine, an institutional server or a container
where installing anything is a request to IT; an interface that needs a
package is an interface that is not available when it is needed.

*No ANSI escapes, no cursor addressing, 80 columns.*  The output must survive
``ssh`` into a minimal container, a Windows console, a screen reader and being
pasted into a methods appendix.  Colour is never the only carrier of meaning
because there is no colour at all.

*Credentials by ``getpass``, stored at 0600, never echoed.*  Keys are typed
without terminal echo, written to a private file in the user's configuration
directory with owner-only permissions, and injected into the environment only
for the duration of a run -- which is the seam :mod:`corpusslr.cli` already
reads them from.  No key is ever printed, logged, written into the review
configuration or included in any artefact; the interface reports *presence*
only, exactly as :func:`corpusslr.cli.credential_status` does.

*No Python exception ever reaches the user.*  Every failure is caught and
restated as a sentence naming what to do next.  A reviewer who has to read a
``KeyError`` to continue has hit an interface defect, not a user error, so the
menu loop treats an unexpected exception as a bug report prompt and returns to
the menu instead of dying.

Run it with ``python -m corpusslr.tui`` or ``corpusslr tui``.
"""
from __future__ import annotations

import contextlib
import getpass as _getpass
import json
import os
import stat
import sys
import textwrap
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import __version__
from .cli import (CONTACT_ENV, CREDENTIAL_ENV, DATABASES, CliError,
                  build_query, compile_for, credential_status, read_corpus,
                  validate_config)

__all__ = [
    "main", "config_home", "credentials_path", "load_credentials",
    "save_credentials", "credential_slots", "Interface", "ReviewSettings",
    "MASK",
]

#: Every line the interface prints is wrapped to this width, so the narrowest
#: terminal anyone still uses (80 columns) never soft-wraps mid-word and the
#: output can be pasted into a methods appendix unchanged.
WIDTH = 78

#: What a credential looks like in output.  The value itself is never
#: rendered; this constant exists so a test can assert that the interface's
#: whole output contains the mask and not the secret.
MASK = "(set, not shown)"

_PERM_MASK = 0o600


# ---------------------------------------------------------------------------
# credential storage
# ---------------------------------------------------------------------------
def config_home() -> str:
    """Directory holding the credentials file and saved settings.

    ``CORPUSSLR_CONFIG_HOME`` wins, then ``XDG_CONFIG_HOME/corpusslr``, then
    ``~/.config/corpusslr``.  The first is what lets the whole storage layer
    be exercised in a temporary directory with no risk of touching a real
    reviewer's keys.
    """
    override = (os.environ.get("CORPUSSLR_CONFIG_HOME") or "").strip()
    if override:
        return override
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    base = xdg or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "corpusslr")


def credentials_path() -> str:
    """Path of the private credentials file."""
    return os.path.join(config_home(), "credentials.json")


def credential_slots() -> List[Dict[str, Any]]:
    """The credential fields the interface offers, derived from the CLI.

    Deliberately *computed* from :data:`corpusslr.cli.CREDENTIAL_ENV` rather
    than listed again here: a second hand-maintained list would drift, and a
    key that the interface stores under a name the CLI does not read is a
    silent "why is Scopus still skipped?" bug.
    """
    slots: List[Dict[str, Any]] = []
    seen = set()
    for alias in sorted(DATABASES):
        spec = CREDENTIAL_ENV.get(alias, {"required": (), "optional": ()})
        label = str(DATABASES[alias]["label"])
        for kind in ("required", "optional"):
            names: Sequence[str] = spec.get(kind, ())
            for name in names:
                if name in seen:
                    continue
                seen.add(name)
                slots.append({
                    "variable": name,
                    "database": label,
                    "alias": alias,
                    "required": kind == "required",
                    "secret": True,
                })
                break            # one canonical variable per kind is enough
    slots.append({"variable": CONTACT_ENV[0],
                  "database": "Crossref, PubMed (politeness contact)",
                  "alias": "", "required": False, "secret": False})
    return slots


def load_credentials() -> Dict[str, str]:
    """Read the stored credentials, returning ``{}`` when there are none.

    A malformed file is reported as empty rather than raising: a truncated
    JSON file must not make the interface unusable, and the remedy (retype the
    key) is the same either way.
    """
    path = credentials_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if str(v).strip()}


def save_credentials(values: Dict[str, str]) -> str:
    """Write *values* with owner-only permissions, returning the path.

    The file is created through :func:`os.open` with mode ``0o600`` so that it
    is never, even briefly, group- or world-readable, and ``chmod`` is applied
    afterwards as well because an existing file keeps its old mode and the
    process umask does not affect an explicit chmod.
    """
    home = config_home()
    os.makedirs(home, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(home, 0o700)
    path = credentials_path()
    payload = json.dumps({k: v for k, v in sorted(values.items()) if v},
                         ensure_ascii=False, indent=1)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _PERM_MASK)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload + "\n")
    finally:
        with contextlib.suppress(OSError):
            os.chmod(path, _PERM_MASK)
    return path


def credentials_mode(path: Optional[str] = None) -> int:
    """Permission bits of the credentials file, ``-1`` when it is absent."""
    target = path or credentials_path()
    try:
        return stat.S_IMODE(os.stat(target).st_mode)
    except OSError:
        return -1


class _EnvironmentPatch:
    """Put stored credentials in the environment for one run, then remove.

    The CLI reads keys from the environment and from nowhere else.  Exporting
    them permanently would leak them into every later child process of the
    shell; setting them for the duration of the run and restoring the previous
    values keeps the blast radius at one function call.
    """

    def __init__(self, values: Dict[str, str]) -> None:
        self._values = {k: v for k, v in values.items() if v}
        self._previous: Dict[str, Optional[str]] = {}

    def __enter__(self) -> "_EnvironmentPatch":
        for name, value in self._values.items():
            self._previous[name] = os.environ.get(name)
            os.environ[name] = value
        return self

    def __exit__(self, *exc: Any) -> None:
        # Returns None, never False-as-bool: a ``__exit__`` annotated to
        # return ``bool`` reads as a context manager that may swallow the
        # exception, and this one must never hide a failure from the reviewer.
        for name, old in self._previous.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
        self._previous.clear()


# ---------------------------------------------------------------------------
# review settings
# ---------------------------------------------------------------------------
class ReviewSettings:
    """The answers collected so far, and the configuration they imply.

    Held as plain attributes rather than a dataclass so that the summary
    rendering, the validation and the JSON serialisation all live next to the
    state they describe.  ``as_config`` is the only place that knows the
    configuration schema, and it never receives a credential.
    """

    def __init__(self) -> None:
        self.title: str = ""
        self.databases: List[str] = []
        self.blocks: List[List[str]] = []
        self.years: Optional[Tuple[int, int]] = None
        self.doc_types: List[str] = []
        self.languages: List[str] = []
        self.files: List[Dict[str, str]] = []
        self.max_results: int = 2000
        self.out_dir: str = "corpusslr_review"
        self.recover_abstracts: bool = True

    # -- rendering ---------------------------------------------------------
    def database_summary(self) -> str:
        if not self.databases:
            return "none chosen yet"
        return ", ".join(str(DATABASES[a]["label"]) for a in self.databases)

    def query_summary(self) -> str:
        if not self.blocks:
            return "not entered yet"
        terms = sum(len(b) for b in self.blocks)
        part = "{} block{}, {} term{}".format(
            len(self.blocks), "" if len(self.blocks) == 1 else "s",
            terms, "" if terms == 1 else "s")
        if self.years:
            part += ", {}-{}".format(self.years[0], self.years[1])
        if self.doc_types:
            part += ", types: " + ", ".join(self.doc_types)
        if self.languages:
            part += ", languages: " + ", ".join(self.languages)
        return part

    def file_summary(self) -> str:
        if not self.files:
            return "none added"
        return "{} file{}".format(len(self.files),
                                  "" if len(self.files) == 1 else "s")

    # -- configuration -----------------------------------------------------
    def as_config(self) -> Dict[str, Any]:
        """The review configuration these answers describe.

        Contains no credential and no contact address by construction: both
        are read from the environment, which is what makes the file safe to
        deposit as supplementary material alongside the manuscript.
        """
        cfg: Dict[str, Any] = {
            "query": {"blocks": [list(b) for b in self.blocks]},
            "databases": [{"name": a} for a in self.databases],
            "files": [dict(f) for f in self.files],
            "dedup": {},
            "enrich": {"recover_abstracts": bool(self.recover_abstracts)},
            "output": {"dir": self.out_dir,
                       "exports": ["csv", "screening", "ris", "bibtex"],
                       "svg": True},
            "max_results": int(self.max_results),
        }
        if self.years:
            cfg["query"]["years"] = [self.years[0], self.years[1]]
        if self.doc_types:
            cfg["query"]["doc_types"] = list(self.doc_types)
        if self.languages:
            cfg["query"]["languages"] = list(self.languages)
        if self.title:
            cfg["review"] = {"title": self.title}
        return cfg

    def missing(self) -> List[str]:
        """What still has to be answered before a run can start."""
        gaps: List[str] = []
        if not self.blocks:
            gaps.append("the search query is empty -- choose menu item 2")
        if not self.databases and not self.files:
            gaps.append("no database and no exported file is selected -- "
                        "choose menu item 1")
        return gaps


# ---------------------------------------------------------------------------
# the interface
# ---------------------------------------------------------------------------
class _Quit(Exception):
    """The reviewer asked to leave, or the input stream ended."""


class Interface:
    """The menu loop.

    Streams and the password reader are injected rather than reached for as
    globals.  That is not a testing afterthought: it is the only way to assert
    -- as the test suite does -- that a typed key appears in *no* byte the
    interface ever writes.
    """

    def __init__(self, stdin: Any = None, stdout: Any = None,
                 getpass_fn: Optional[Callable[..., str]] = None,
                 runner: Optional[Callable[..., int]] = None) -> None:
        self._stdin = stdin
        self._out = stdout if stdout is not None else sys.stdout
        self._getpass = getpass_fn
        self._runner = runner
        self.settings = ReviewSettings()
        self.credentials: Dict[str, str] = {}
        self.last_run: Dict[str, Any] = {}

    # -- output ------------------------------------------------------------
    def say(self, text: str = "") -> None:
        """Print one wrapped paragraph.  No escape sequences, ever."""
        if not text:
            self._out.write("\n")
        else:
            for line in text.split("\n"):
                if not line.strip():
                    self._out.write("\n")
                    continue
                indent = line[:len(line) - len(line.lstrip())]
                for wrapped in textwrap.wrap(
                        line, width=WIDTH, break_long_words=False,
                        break_on_hyphens=False,
                        subsequent_indent=indent) or [""]:
                    self._out.write(wrapped + "\n")
        self._out.flush()

    def raw(self, text: str) -> None:
        """Print a pre-formatted line (a table row) without rewrapping.

        Truncated at :data:`WIDTH` because the callers are fixed-width table
        rows whose overflow is a cosmetic label, never data.  Anything the
        reviewer may need to copy verbatim -- a compiled query above all --
        goes through :meth:`verbatim` instead, which never drops a character.
        """
        self._out.write(text[:WIDTH] + "\n")
        self._out.flush()

    def row(self, label: str, value: str) -> None:
        """Print a ``label : value`` status row, wrapping long values.

        Clipping here would hide exactly the thing the row exists to show --
        seven selected databases do not fit in 80 columns, and a reviewer who
        cannot see the tail of the list cannot tell what will be searched.
        The continuation lines are indented to the value column so the row
        still reads as one entry.
        """
        head = "{:<14}: ".format(label[:14])
        for line in textwrap.wrap(value, width=WIDTH - len(head),
                                  break_long_words=False,
                                  break_on_hyphens=False,
                                  initial_indent=head,
                                  subsequent_indent=" " * len(head)) or [head]:
            self._out.write(line + "\n")
        self._out.flush()

    def verbatim(self, text: str, indent: str = "    ") -> None:
        """Print *text* wrapped only at spaces, never truncated or hyphenated.

        A compiled search string is data: a line broken inside a term, or cut
        off at the right margin, produces a query that does not run and a
        methods section that misreports what was searched.  Long unbreakable
        tokens are therefore allowed to overflow the margin rather than be
        split.
        """
        for line in textwrap.wrap(text, width=WIDTH - len(indent),
                                  break_long_words=False,
                                  break_on_hyphens=False,
                                  initial_indent=indent,
                                  subsequent_indent=indent) or [indent]:
            self._out.write(line + "\n")
        self._out.flush()

    def rule(self, char: str = "-") -> None:
        self.raw(char * WIDTH)

    # -- input -------------------------------------------------------------
    def _input_echoes(self) -> bool:
        """Whether the terminal itself will echo the reviewer's keystrokes.

        On an interactive terminal it does, and the newline from pressing
        Enter moves the cursor for us.  When input is piped, redirected from a
        file or injected by a test, nothing echoes -- and without the newline
        below every prompt runs into the text that follows it, producing lines
        far wider than 80 columns and messages split in the middle.  So the
        newline is supplied exactly when the terminal will not.
        """
        stream = self._stdin if self._stdin is not None else sys.stdin
        try:
            return bool(stream.isatty())
        except (AttributeError, ValueError, OSError):
            return False

    def ask(self, prompt: str, default: str = "") -> str:
        """Read one line.  End of input is a request to quit, not a crash."""
        shown = prompt if not default else "{} [{}]".format(prompt, default)
        self._out.write(shown + " ")
        self._out.flush()
        echoes = self._input_echoes()
        try:
            if self._stdin is None:
                line = input()
            else:
                raw = self._stdin.readline()
                if raw == "":
                    raise EOFError
                line = raw.rstrip("\r\n")
        except EOFError:
            raise _Quit
        except KeyboardInterrupt:                          # pragma: no cover
            raise _Quit
        except (OSError, ValueError):
            # No usable terminal at all (a detached process, a captured
            # stdin). Leaving is the only honest outcome, and it must not be
            # a traceback.
            self._out.write("\n")
            self.say("There is no terminal to read from here. Run "
                     "\"corpusslr tui\" from an interactive shell, or drive "
                     "the review from a configuration file with "
                     "\"corpusslr run -c review.json\".")
            raise _Quit
        if not echoes:
            self._out.write("\n")
        value = line.strip()
        return value or default

    def ask_secret(self, prompt: str) -> str:
        """Read a credential without echoing it.

        An empty answer is a normal outcome (the reviewer changed their mind),
        and a terminal that cannot switch echo off is a warning rather than a
        failure -- but the fallback still never writes the value back out.
        """
        reader = self._getpass or _getpass.getpass
        try:
            value = reader(prompt + " ")
        except EOFError:
            raise _Quit
        except _getpass.GetPassWarning:                    # pragma: no cover
            self.say("Warning: this terminal cannot switch echo off, so what "
                     "you type may be visible on screen. It is still not "
                     "written to any log or file other than the private "
                     "credentials file.")
            return ""
        except (OSError, ValueError):                      # pragma: no cover
            self.say("This terminal cannot read a hidden password. Set the "
                     "key as an environment variable in your shell instead, "
                     "then restart: export SCOPUS_API_KEY=...")
            return ""
        return (value or "").strip()

    def confirm(self, prompt: str, default: bool = False) -> bool:
        suffix = "Y/n" if default else "y/N"
        answer = self.ask("{} ({})".format(prompt, suffix)).lower()
        if not answer:
            return default
        return answer.startswith(("y", "t"))

    # ------------------------------------------------------------------
    def pause(self) -> None:
        self.ask("Press Enter to return to the menu.")

    # -- screens -----------------------------------------------------------
    def banner(self) -> None:
        self.rule("=")
        self.raw("CorpusSLR {} -- guided systematic review".format(__version__))
        self.rule("=")
        self.say("This walks you through one complete search: which databases "
                 "to query, the query itself, deduplication, the PRISMA 2020 "
                 "flow counts and the files you hand to your screening tool. "
                 "You never have to write any code.")
        self.say("Nothing is retrieved until you choose \"Run\", and you can "
                 "always inspect the plan first.")

    def status(self) -> None:
        s = self.settings
        self.rule()
        self.row("Review", s.title or "(untitled)")
        self.row("Databases", s.database_summary())
        self.row("Query", s.query_summary())
        self.row("File exports", s.file_summary())
        self.row("API keys", self._credential_line())
        self.row("Output folder", s.out_dir)
        self.row("Record limit", "{} per database".format(s.max_results))
        self.rule()

    def _credential_line(self) -> str:
        """Presence only.  The value is never part of any rendered string."""
        present = [slot["variable"] for slot in credential_slots()
                   if self.credentials.get(str(slot["variable"]), "")
                   or (os.environ.get(str(slot["variable"])) or "").strip()]
        if not present:
            return "none stored (only free databases will work)"
        return "{} {}".format(", ".join(present), MASK)

    MENU: Tuple[Tuple[str, str], ...] = (
        ("1", "Choose databases"),
        ("2", "Enter the search query"),
        ("3", "Set API keys (typed hidden, stored privately)"),
        ("4", "Add an exported file (Embase, IEEE, EBSCOhost, ...)"),
        ("5", "Output folder and record limit"),
        ("6", "Check the plan -- shows the query, retrieves nothing"),
        ("7", "Run the review"),
        ("8", "Save or load these settings"),
        ("9", "Help: what each step does and why"),
        ("0", "Quit"),
    )

    def menu(self) -> str:
        self.say()
        for key, label in self.MENU:
            self.raw("  {}) {}".format(key, label))
        self.say()
        return self.ask("Choose an item (0-9):")

    # ------------------------------------------------------------------
    def run(self) -> int:
        """The whole session.  Returns a process exit code."""
        self.credentials = load_credentials()
        self._check_permissions()
        self.banner()
        actions: Dict[str, Callable[[], None]] = {
            "1": self.screen_databases,
            "2": self.screen_query,
            "3": self.screen_keys,
            "4": self.screen_files,
            "5": self.screen_output,
            "6": self.screen_check,
            "7": self.screen_run,
            "8": self.screen_settings,
            "9": self.screen_help,
        }
        while True:
            self.status()
            try:
                choice = self.menu()
            except _Quit:
                self.say()
                self.say("Leaving. Nothing was sent anywhere.")
                return 0
            if choice in ("0", "q", "quit", "exit"):
                self.say("Done. Your settings file and any results stay in "
                         "{}.".format(self.settings.out_dir))
                return 0
            action = actions.get(choice)
            if action is None:
                self.say("I did not recognise {!r}. Type the number of a menu "
                         "item, for example 1 to choose databases, or 0 to "
                         "quit.".format(choice))
                continue
            try:
                action()
            except _Quit:
                self.say()
                self.say("Cancelled that step; back to the menu.")
            except CliError as exc:
                self.say("That will not work yet: {}".format(exc))
                self.pause()
            except OSError as exc:
                self.say("The file system refused that: {}. Check that the "
                         "folder exists and that you can write to it."
                         .format(exc))
                self.pause()
            except Exception as exc:                           # noqa: BLE001
                # An unexpected exception here is an interface defect: the
                # reviewer must not be the one to read the traceback, and the
                # session must survive it.
                self.say("Something inside CorpusSLR went wrong ({}: {}). "
                         "This is a defect, not your mistake -- your answers "
                         "are still here, and you can try another menu item. "
                         "Please report it at "
                         "https://github.com/s-matysik/CorpusSLR/issues"
                         .format(type(exc).__name__, exc))
                self.pause()

    def _check_permissions(self) -> None:
        mode = credentials_mode()
        if mode >= 0 and mode & 0o077:
            self.say("Note: the credentials file {} was readable by other "
                     "users; its permissions have been tightened to "
                     "owner-only.".format(credentials_path()))
            save_credentials(self.credentials)

    # -- 1. databases ------------------------------------------------------
    def screen_databases(self) -> None:
        aliases = sorted(DATABASES)
        self.say()
        self.say("Which databases should the search cover? Multi-database "
                 "searching is a PRISMA-S expectation (Item 1): one database "
                 "never covers a field on its own.")
        self.say()
        for i, alias in enumerate(aliases, 1):
            need = ("needs an API key from your library"
                    if not DATABASES[alias]["keyless"]
                    else "free, no key needed")
            self.raw("  {:>2}) {:<34} {}".format(
                i, str(DATABASES[alias]["label"])[:34], need))
        self.say()
        self.say("Type the numbers separated by commas (for example 3,5,7), "
                 "or the word \"free\" for every database that needs no key, "
                 "or \"none\" to clear the selection.")
        answer = self.ask("Databases:")
        chosen = self._parse_database_answer(answer, aliases)
        if chosen is None:
            return
        self.settings.databases = chosen
        if not chosen:
            self.say("Selection cleared.")
            return
        self.say("Selected: " + self.settings.database_summary())
        needs = [a for a in chosen if not DATABASES[a]["keyless"]]
        missing = [a for a in needs
                   if not credential_status(a)["credential_present"]
                   and not self._stored_for(a)]
        if missing:
            self.say()
            self.say("These need an API key that is not set yet: {}. Use menu "
                     "item 3 to enter it, or the run will skip them and say "
                     "so in the report.".format(
                         ", ".join(str(DATABASES[a]["label"])
                                   for a in missing)))

    def _stored_for(self, alias: str) -> bool:
        spec = CREDENTIAL_ENV.get(alias, {"required": (), "optional": ()})
        return any(self.credentials.get(n, "").strip()
                   for n in spec.get("required", ()))

    def _parse_database_answer(self, answer: str,
                               aliases: List[str]) -> Optional[List[str]]:
        """Turn what was typed into aliases, or explain and return ``None``.

        Numbers, canonical names and the spellings :mod:`corpusslr.cli`
        already accepts ("Web of Science", "MEDLINE") are all understood,
        because rejecting a reviewer's own institutional name for a database
        is pedantry rather than validation.
        """
        from .cli import _norm_db
        text = answer.strip().lower()
        if not text:
            self.say("Nothing entered; the selection is unchanged.")
            return None
        if text in ("none", "clear", "-"):
            return []
        if text in ("free", "keyless", "open"):
            return [a for a in aliases if DATABASES[a]["keyless"]]
        if text in ("all", "everything", "*"):
            return list(aliases)
        picked: List[str] = []
        for token in [t.strip() for t in text.replace(";", ",").split(",")]:
            if not token:
                continue
            alias = ""
            if token.isdigit():
                index = int(token)
                if 1 <= index <= len(aliases):
                    alias = aliases[index - 1]
                else:
                    self.say("There is no database number {} in the list; the "
                             "numbers go from 1 to {}. Nothing was changed."
                             .format(index, len(aliases)))
                    return None
            else:
                alias = _norm_db(token)
            if not alias:
                self.say("I do not know a database called {!r}. Type the "
                         "number shown next to it in the list above, or one "
                         "of these names: {}. Databases without an open API "
                         "(Embase, Cochrane CENTRAL, EBSCOhost, ProQuest, "
                         "IEEE Xplore) are added as exported files with menu "
                         "item 4 instead. Nothing was changed."
                         .format(answer.strip(), ", ".join(aliases)))
                return None
            if alias not in picked:
                picked.append(alias)
        if not picked:
            self.say("Nothing recognised in {!r}; the selection is "
                     "unchanged.".format(answer.strip()))
            return None
        return picked

    # -- 2. query ----------------------------------------------------------
    def screen_query(self) -> None:
        self.say()
        self.say("A CorpusSLR query is a set of blocks. Inside a block the "
                 "terms are alternatives (OR); the blocks are then combined "
                 "with AND. This is the standard three-block pattern: what "
                 "the technology is, what it does, and where it is applied.")
        self.say()
        self.raw("  block 1: artificial intelligence, machine learning")
        self.raw("  block 2: adoption, acceptance")
        self.raw("  block 3: small business, SME")
        self.say()
        self.say("means (artificial intelligence OR machine learning) AND "
                 "(adoption OR acceptance) AND (small business OR SME).")
        self.say()
        self.say("Type one block per line, terms separated by commas. Press "
                 "Enter on an empty line when you are finished.")
        blocks: List[List[str]] = []
        while True:
            line = self.ask("  block {}:".format(len(blocks) + 1))
            if not line:
                break
            terms = [t.strip() for t in line.split(",") if t.strip()]
            short = [t for t in terms if len(t) < 2]
            if short:
                self.say("  {} is too short to be a search term; a "
                         "one-character term matches almost everything. "
                         "Retype this block.".format(
                             ", ".join(repr(t) for t in short)))
                continue
            if not terms:
                self.say("  That line had no terms in it. Retype it, or press "
                         "Enter on an empty line to finish.")
                continue
            blocks.append(terms)
        if not blocks:
            self.say("No blocks entered; the query is unchanged.")
            return
        self.settings.blocks = blocks
        self.say()
        years = self.ask("Publication years, as \"from-to\" (Enter for no "
                         "limit):")
        self.settings.years = self._parse_years(years)
        self.say("Document types: article, review, conference, chapter, "
                 "book.")
        types = self.ask("Types, comma separated (Enter for all):")
        self.settings.doc_types = [t.strip().lower()
                                   for t in types.split(",") if t.strip()]
        langs = self.ask("Languages as two-letter codes, e.g. en,pl (Enter "
                         "for all):")
        self.settings.languages = [t.strip().lower()
                                   for t in langs.split(",") if t.strip()]
        self.say()
        self.say("Query recorded: " + self.settings.query_summary())
        self.say("Menu item 6 shows exactly how each database will receive "
                 "it, which is what PRISMA-S Item 8 asks you to report.")

    def _parse_years(self, text: str) -> Optional[Tuple[int, int]]:
        raw = text.strip()
        if not raw:
            return None
        parts = [p.strip() for p in raw.replace("..", "-").replace(
            "to", "-").replace(",", "-").split("-") if p.strip()]
        try:
            if len(parts) == 1:
                y1 = y2 = int(parts[0])
            else:
                y1, y2 = int(parts[0]), int(parts[1])
        except ValueError:
            self.say("I could not read {!r} as a year range. Write it as two "
                     "years with a dash, for example 2015-2026. No year "
                     "limit was set.".format(raw))
            return None
        if y1 > y2:
            y1, y2 = y2, y1
            self.say("Swapped the years so the range reads {}-{}.".format(
                y1, y2))
        if y1 < 1500 or y2 > 2100:
            self.say("{}-{} is outside the plausible range 1500-2100, so no "
                     "year limit was set.".format(y1, y2))
            return None
        return (y1, y2)

    # -- 3. credentials ----------------------------------------------------
    def screen_keys(self) -> None:
        slots = credential_slots()
        self.say()
        self.say("Subscription databases need a key that your library issues. "
                 "What you type is not shown on screen, is stored only in {} "
                 "with owner-only permissions, and is never written into the "
                 "review configuration, the reports or any log -- so those "
                 "files stay safe to deposit as supplementary material."
                 .format(credentials_path()))
        self.say()
        for i, slot in enumerate(slots, 1):
            name = str(slot["variable"])
            stored = bool(self.credentials.get(name, "").strip())
            from_env = bool((os.environ.get(name) or "").strip())
            if stored:
                state = MASK
            elif from_env:
                state = "(set in your shell)"
            else:
                state = "not set"
            self.raw("  {:>2}) {:<28} {:<12} {}".format(
                i, name, "required" if slot["required"] else "optional",
                state))
        self.say()
        answer = self.ask("Which one do you want to set? (number, or Enter to "
                          "go back):")
        if not answer:
            return
        if not answer.isdigit() or not 1 <= int(answer) <= len(slots):
            self.say("Type one of the numbers shown, from 1 to {}, or press "
                     "Enter to go back.".format(len(slots)))
            return
        slot = slots[int(answer) - 1]
        name = str(slot["variable"])
        if not slot["secret"]:
            value = self.ask("{} (an email address for the polite contact "
                             "header):".format(name))
            if not value:
                self.say("Nothing entered; {} is unchanged.".format(name))
                return
            self.credentials[name] = value
        else:
            value = self.ask_secret("{} (typed hidden):".format(name))
            if not value:
                self.say("Nothing entered, so {} was left as it was. Nothing "
                         "was deleted and nothing broke -- choose the number "
                         "again when you have the key.".format(name))
                return
            self.credentials[name] = value
        path = save_credentials(self.credentials)
        mode = credentials_mode(path)
        self.say("Stored {} in {} (permissions {}). The value itself is not "
                 "shown again anywhere.".format(name, path,
                                                oct(mode)[-3:]))

    # -- 4. file exports ---------------------------------------------------
    def screen_files(self) -> None:
        self.say()
        self.say("Databases without an open API -- Embase, Cochrane CENTRAL, "
                 "EBSCOhost, ProQuest, IEEE Xplore, ACM -- are covered by "
                 "downloading their export file from the web interface and "
                 "adding it here. CorpusSLR reads RIS, BibTeX, PubMed .nbib, "
                 "Web of Science tagged, EndNote XML, .enw, vendor CSV and "
                 "saved HTML tables, and detects which one it is.")
        self.say()
        if self.settings.files:
            self.say("Already added:")
            for i, entry in enumerate(self.settings.files, 1):
                # The database label comes first and the path second: an
                # export path is routinely longer than the terminal is wide,
                # and clipping it must not take the label with it -- the label
                # is what tells the reviewer which database this file covers.
                self.say("  {}) {} -- {}".format(
                    i, entry.get("database", "unspecified"),
                    entry.get("path", "")))
            self.say()
        path = self.ask("Path of the export file (Enter to go back):")
        if not path:
            return
        expanded = os.path.expanduser(path)
        if not os.path.isfile(expanded):
            self.say("There is no readable file at {}. Check the path -- if "
                     "it contains spaces, type it without quotes. Nothing was "
                     "added.".format(expanded))
            return
        label = self.ask("Which database did this come from? (free text, it "
                         "goes into the PRISMA-S appendix):", "unspecified")
        entry = {"path": expanded, "database": label}
        note = self.ask("The query you ran there, as you ran it (Enter to "
                        "skip -- PRISMA-S Item 8 asks for it):")
        if note:
            entry["query"] = note
        self.settings.files.append(entry)
        self.say("Added. {} now queued for import.".format(
            self.settings.file_summary()))

    # -- 5. output ---------------------------------------------------------
    def screen_output(self) -> None:
        self.say()
        current = self.settings.out_dir
        answer = self.ask("Folder for the results:", current)
        self.settings.out_dir = os.path.expanduser(answer) or current
        cap = self.ask("Maximum records per database:",
                       str(self.settings.max_results))
        try:
            value = int(str(cap).strip())
            if value <= 0:
                raise ValueError
            self.settings.max_results = value
        except ValueError:
            self.say("{!r} is not a whole number above zero, so the limit "
                     "stays at {}.".format(cap, self.settings.max_results))
        self.settings.recover_abstracts = self.confirm(
            "Try to recover missing abstracts from Crossref and PubMed?",
            self.settings.recover_abstracts)
        # Every accepted value is echoed back. A silently accepted setting is
        # one the reviewer cannot verify, and the record cap in particular
        # changes how many records the review reports as identified.
        self.say("Results will be written to {}.".format(
            self.settings.out_dir))
        self.say("At most {} records per database; abstract recovery is {}."
                 .format(self.settings.max_results,
                         "on" if self.settings.recover_abstracts else "off"))

    # -- 6. check ----------------------------------------------------------
    def screen_check(self) -> None:
        gaps = self.settings.missing()
        if gaps:
            self.say()
            for gap in gaps:
                self.say("  - " + gap)
            return
        cfg = validate_config(self.settings.as_config(), "your answers")
        query = build_query(cfg)
        self.say()
        self.say("This is the plan. Nothing has been retrieved.")
        self.say()
        with _EnvironmentPatch(self.credentials):
            for spec in cfg.get("databases") or []:
                alias = str(spec["name"])
                status = credential_status(alias)
                compiled = compile_for(alias, query)
                self.raw("{}:".format(status["database"]))
                self.verbatim(str(compiled.get("query", "")))
                if status["requires_credential"]:
                    self.raw("    key: {}".format(
                        "present" if status["credential_present"]
                        else "MISSING -- this database would be skipped"))
                filters = str(compiled.get("filters", "") or "")
                if filters:
                    self.verbatim("filters: " + filters)
                self.say()
        for entry in cfg.get("files") or []:
            self.raw("file: {}".format(entry.get("path", "")))
        for warning in dict.fromkeys(query.warnings):
            self.say("Warning: {}".format(warning))
        self.say("Copy the lines above into your methods section: they are "
                 "the full search strategies as run, which is PRISMA-S "
                 "Item 8.")

    # -- 7. run ------------------------------------------------------------
    def screen_run(self) -> None:
        gaps = self.settings.missing()
        if gaps:
            self.say()
            self.say("Not ready to run yet:")
            for gap in gaps:
                self.say("  - " + gap)
            return
        cfg = validate_config(self.settings.as_config(), "your answers")
        out_dir = self.settings.out_dir
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            self.say("I cannot create the folder {}: {}. Choose a different "
                     "one with menu item 5.".format(out_dir, exc))
            return
        cfg_path = os.path.join(out_dir, "review.json")
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=1, sort_keys=True)
        self.say()
        self.say("Wrote the search strategy to {}. It contains no keys, so "
                 "you can deposit it with the manuscript; anyone can rerun "
                 "the whole review with: corpusslr run -c {}"
                 .format(cfg_path, cfg_path))
        self.say()
        self.say("Retrieving now. This can take several minutes; the "
                 "databases are rate-limited on purpose and each line below "
                 "reports progress.")
        self.say()
        runner = self._runner or _default_runner
        argv = ["run", "-c", cfg_path, "-C", out_dir, "--keep-going"]
        with _EnvironmentPatch(self.credentials):
            code = int(runner(argv, self._out))
        self.say()
        if code != 0:
            self.say("The run stopped with code {}. The lines above say what "
                     "failed; the most common causes are a missing API key "
                     "(menu item 3), a query that matched nothing (menu item "
                     "2), or no internet connection.".format(code))
            self.pause()
            return
        self.last_run = {"config": cfg_path, "out_dir": out_dir}
        self._after_run(out_dir)

    def _after_run(self, out_dir: str) -> None:
        """Write the Scopus-format CSV and tell the reviewer what to do next.

        The canonical post-deduplication export is the Scopus CSV layout
        because that is what bibliometrix, VOSviewer and EmbedSLR read without
        conversion; the run itself has already written the generic CSV, the
        screening CSV, RIS and BibTeX.
        """
        unique = os.path.join(out_dir, "corpus_unique.json")
        if not os.path.isfile(unique):
            return
        try:
            corpus, _result = read_corpus(unique)
        except Exception as exc:                               # noqa: BLE001
            self.say("The corpus was retrieved but I could not reopen {} to "
                     "write the Scopus-format export ({}). The other export "
                     "files in {} are complete."
                     .format(unique, exc, out_dir))
            return
        target = os.path.join(out_dir, "corpus_scopus.csv")
        _write_scopus_csv(corpus.records, target)
        self.say("Files you can use now, all in {}:".format(out_dir))
        self.raw("  corpus_scopus.csv   the deduplicated corpus in Scopus "
                 "column format")
        self.raw("  screening.csv       title/abstract list for ASReview, "
                 "Rayyan or a spreadsheet")
        self.raw("  prisma_s_appendix.md  the search-reporting appendix "
                 "(PRISMA-S)")
        self.raw("  prisma2020_flow.svg the PRISMA 2020 flow diagram")
        self.raw("  dedup_report.csv    every duplicate decision, with the "
                 "rule that made it")
        self.raw("  run_summary.json    counts, version and configuration "
                 "checksum")
        self.say()
        self.say("Next: screen the titles and abstracts, then come back and "
                 "put your screening counts into the configuration file so "
                 "the PRISMA diagram shows the whole review.")

    # -- 8. settings -------------------------------------------------------
    def screen_settings(self) -> None:
        self.say()
        self.say("Your answers can be saved to a small JSON file and reloaded "
                 "later, or handed to a colleague. It never contains a key.")
        self.say()
        self.raw("  1) Save the settings to a file")
        self.raw("  2) Load settings from a file")
        self.say()
        choice = self.ask("Choose 1 or 2 (Enter to go back):")
        if choice == "1":
            path = self.ask("Save to:", os.path.join(self.settings.out_dir,
                                                     "review.json"))
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
            cfg = self.settings.as_config()
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, ensure_ascii=False, indent=1,
                          sort_keys=True)
            self.say("Saved to {}.".format(path))
        elif choice == "2":
            path = self.ask("Load from:")
            if not path:
                return
            expanded = os.path.expanduser(path)
            if not os.path.isfile(expanded):
                self.say("There is no readable file at {}. Nothing was "
                         "loaded.".format(expanded))
                return
            try:
                with open(expanded, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except ValueError as exc:
                self.say("{} is not valid JSON ({}). If you edited it by "
                         "hand, a missing comma or quote is the usual cause. "
                         "Nothing was loaded.".format(expanded, exc))
                return
            cfg = validate_config(data, expanded)
            self._adopt(cfg)
            self.say("Loaded. " + self.settings.query_summary())

    def _adopt(self, cfg: Dict[str, Any]) -> None:
        """Replace the current answers with a validated configuration."""
        s = ReviewSettings()
        q = cfg.get("query") or {}
        s.blocks = [list(b) for b in (q.get("blocks") or [])]
        years = q.get("years")
        if years:
            s.years = (int(years[0]), int(years[1]))
        s.doc_types = list(q.get("doc_types") or [])
        s.languages = list(q.get("languages") or [])
        s.databases = [str(d["name"]) for d in (cfg.get("databases") or [])]
        s.files = [{str(k): str(v) for k, v in dict(f).items()}
                   for f in (cfg.get("files") or [])]
        out = cfg.get("output") or {}
        s.out_dir = str(out.get("dir") or self.settings.out_dir)
        s.max_results = int(cfg.get("max_results") or 2000)
        s.recover_abstracts = bool(
            (cfg.get("enrich") or {}).get("recover_abstracts", True))
        s.title = str((cfg.get("review") or {}).get("title") or "")
        self.settings = s

    # -- 9. help -----------------------------------------------------------
    def screen_help(self) -> None:
        self.say()
        self.say("What the steps are for")
        self.rule()
        for heading, body in _HELP:
            self.say(heading)
            self.say("  " + body)
            self.say()
        self.pause()


_HELP: Tuple[Tuple[str, str], ...] = (
    ("Databases",
     (
      "A systematic review searches several databases because none is "
      "complete. Gusenbauer and Haddaway (2020) distinguish principal search "
      "systems, which can carry a review on their own -- Scopus, Web of "
      "Science, PubMed -- from supplementary ones. Include at least one "
      "principal system; add free sources on top rather than instead."
     )),
    ("The query",
     (
      "Blocks of synonyms combined with AND is the pattern reviewers are "
      "expected to report. Writing it once and letting CorpusSLR translate it "
      "into each database's own syntax removes the most common inconsistency "
      "in multi-database searches: a query that quietly means something "
      "different in each interface."
     )),
    ("API keys",
     (
      "Scopus and Web of Science need an institutional key; your library "
      "issues it. Everything else here works without one, so a review is "
      "still possible with no subscription -- the report records which "
      "databases were reachable and which were not."
     )),
    ("Deduplication",
     (
      "The same article arrives from several databases. CorpusSLR matches on "
      "identifiers first, then on title similarity with a year tolerance, and "
      "writes down which rule removed which record, so the duplicate count in "
      "your PRISMA diagram can be audited rather than trusted."
     )),
    ("PRISMA and PRISMA-S",
     (
      "The flow diagram reports how many records were identified, removed as "
      "duplicates, screened and included; the PRISMA-S appendix reports how "
      "the search itself was conducted. Both are produced from the actual run, "
      "not typed in by hand, which is what makes the numbers reproducible."
     )),
    ("The export you hand on",
     (
      "After deduplication the corpus is written in the Scopus CSV column "
      "layout, which bibliometrix, VOSviewer and EmbedSLR all read without "
      "conversion, plus a narrow screening CSV for ASReview or Rayyan."
     )),
)


# ---------------------------------------------------------------------------
# helpers shared with the CLI subcommand
# ---------------------------------------------------------------------------
def _write_scopus_csv(records: Any, path: str) -> str:
    """Write the deduplicated corpus in the Scopus CSV column layout.

    This is the canonical hand-off format after deduplication: bibliometrix,
    VOSviewer and EmbedSLR all read a Scopus export without conversion, so
    emitting CorpusSLR's own column names here would make the reviewer do a
    rename step that no downstream tool documents.
    """
    from .export import to_scopus_csv
    return to_scopus_csv(records, path)


def _default_runner(argv: List[str], out: Any) -> int:
    """Run the CLI in-process, with its progress visible in this terminal."""
    from .cli import main as cli_main
    return int(cli_main(argv, stdout=_Sink(), stderr=out))


class _Sink:
    """Swallow the CLI's JSON data product.

    ``corpusslr run`` writes a machine-readable summary to stdout for
    pipelines.  Printing a page of JSON at a reviewer who is being guided
    through a menu is noise -- the same numbers are in ``run_summary.json``
    and in the lines the interface prints itself.
    """

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        return None


def main(argv: Optional[Sequence[str]] = None, stdin: Any = None,
         stdout: Any = None, getpass_fn: Optional[Callable[..., str]] = None,
         runner: Optional[Callable[..., int]] = None) -> int:
    """Start the guided interface and return a process exit code.

    *stdin*, *stdout*, *getpass_fn* and *runner* are injection seams: they are
    what lets the whole interface be driven from a test with no terminal, no
    network and no real credential, including the assertion that a typed key
    never reaches any output stream.
    """
    if argv:
        unknown = [a for a in argv if a not in ("-h", "--help")]
        if unknown:
            (stdout or sys.stdout).write(
                "corpusslr tui takes no arguments; it asks its questions "
                "instead. Ignoring: {}\n".format(" ".join(unknown)))
    interface = Interface(stdin=stdin, stdout=stdout, getpass_fn=getpass_fn,
                          runner=runner)
    try:
        return interface.run()
    except KeyboardInterrupt:                              # pragma: no cover
        interface.say()
        interface.say("Interrupted. Nothing was lost that was already "
                      "written to disk.")
        return 130


if __name__ == "__main__":                                 # pragma: no cover
    sys.exit(main(sys.argv[1:]))
