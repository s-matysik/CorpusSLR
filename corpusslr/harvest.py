"""Reproducible harvesting: raw-response archiving, offline replay, drift audit.

PRISMA-S (Rethlefsen et al., 2021, *Systematic Reviews* 10:39) asks authors to
report every search so that it can be *repeated*.  For an API-native review
that promise is weaker than it looks: bibliographic databases grow daily,
relevance rankings are re-tuned, records are corrected, and citation counters
change by the hour.  Re-running the identical query six months later therefore
returns a *different* set - which is scientifically normal but, undocumented,
makes the review unauditable.

This module separates the two properties that are usually conflated:

*Reproducibility* - a third party re-runs the analysis on the **archived
evidence** and obtains the identical record set.  Implemented here by writing
every raw HTTP response to disk (:class:`HarvestArchive`) and letting the very
same harvesting call run against that archive with the network switched off
(``harvest(..., replay=True)`` via :class:`ReplaySession`).  This is a
deterministic, bit-level guarantee and it is what a reviewer should be given.

*Replicability* - the same query is executed **against the live database** at a
later date and the difference is quantified rather than hidden
(:func:`compare_harvests`).  Records added, removed and changed are reported
explicitly; volatile counters are reported separately so that "the databases
grew" is never mistaken for "the search was unstable".

Design decisions that carry methodological weight:

1. The record-set checksum (:func:`records_checksum`) is computed over
   *stable* bibliographic fields only.  Citation counts, open-access flags and
   abstract wording change without the underlying study changing, so including
   them would make every re-harvest look like a different corpus.
2. Records are returned in a canonical order (:func:`sort_records`).  Both
   Crossref and Semantic Scholar return relevance-ranked results whose order is
   not contractual; sorting by DOI and normalized title makes the checksum, the
   exports and any downstream diff independent of ranking.
3. Credentials never reach the archive.  API keys and tokens are dropped, and
   contact e-mail addresses are redacted, both from the stored request and from
   the request key - so a reviewer replays the archive with no credentials at
   all.

The layer is source-agnostic: it wraps the ``requests``-style session that
every :class:`~corpusslr.sources.base.BaseSource` already uses, so it works
unchanged for Crossref and Semantic Scholar (both keyless and therefore the
sources a reviewer can actually re-run) as well as for the credentialed
principal sources.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import (Any, Dict, Iterable, List, Optional, Sequence, Tuple,
                    Union)

from .corpus import SearchEvent, SourceResult
from .record import Record, normalize_title

#: Archive format version, written to ``manifest.json``.  A reader that finds a
#: higher number than it knows must refuse to replay rather than guess.
ARCHIVE_VERSION = 1

#: Conservative default when the caller does not cap the harvest explicitly.
DEFAULT_MAX_RESULTS = 1000

#: Request parameters that must never be written to the archive: they identify
#: the subscriber, not the search.  They are also excluded from the request key
#: so that an archive recorded with a key replays without one.
SECRET_PARAMS = frozenset({
    "apikey", "api_key", "key", "token", "insttoken", "access_token",
    "x-api-key", "api-key", "subscriber", "password",
})

#: Parameters that are personal data rather than secrets (politeness contact
#: addresses required by Crossref, OpenAlex and NCBI).  They are stored
#: redacted and excluded from the request key, so a reviewer may - and should -
#: replay with their own address.
PRIVATE_PARAMS = frozenset({"mailto", "email", "tool", "api_email"})

#: Response headers worth keeping as evidence (rate-limit and version
#: signalling).  Everything else is noise or identifies the client.
_KEPT_HEADERS = ("content-type", "date", "x-api-version", "x-rate-limit-limit",
                 "x-rate-limit-interval", "x-ratelimit-limit",
                 "x-ratelimit-remaining", "retry-after", "etag", "link")

#: Bibliographic fields that enter the record checksum.  Deliberately excludes
#: ``cited_by`` (a counter), ``open_access`` (re-evaluated by the provider),
#: ``url`` (resolver churn) and the abstract *text* - only its presence is
#: checksummed, because gaining an abstract is a metadata change worth seeing
#: while re-wrapped whitespace is not.
CHECKSUM_FIELDS: Tuple[str, ...] = (
    "doi", "pmid", "openalex_id", "scopus_id", "norm_title", "year",
    "norm_journal", "issn", "volume", "issue", "pages", "doc_type",
    "language", "first_author_surname", "n_authors", "has_abstract",
)

#: Fields that legitimately change between two harvests of the same query
#: without indicating drift in the corpus; reported separately by
#: :func:`compare_harvests`.
VOLATILE_FIELDS: Tuple[str, ...] = ("cited_by", "open_access")

#: Fields assigned by :class:`~corpusslr.corpus.Corpus` at registration time,
#: not by the source, hence ignored when comparing a live and a replayed
#: harvest for equality.
_ASSIGNED_FIELDS = ("uid", "search_id", "provenance")

_WS = re.compile(r"\s+")


class HarvestError(RuntimeError):
    """Archive is unusable, incomplete, tampered with, or replay diverged."""


# ----------------------------------------------------------------------------
# canonical serialization helpers
# ----------------------------------------------------------------------------
def _canon(obj: Any) -> str:
    """Canonical JSON: sorted keys, no whitespace, Unicode preserved.

    Checksums must be stable across Python versions, dict insertion order and
    platforms, so every hashed structure passes through this one function.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utcnow() -> str:
    """UTC timestamp, second resolution, explicit ``Z`` suffix."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def redact_params(params: Optional[dict]) -> Dict[str, str]:
    """Return request parameters safe to archive.

    Secrets are removed entirely (their mere length can leak information about
    a key), contact addresses are replaced by a marker so that the *fact* that
    a polite-pool address was sent stays documented - it is part of the request
    as executed, which PRISMA-S item 8 asks for
    the interface used, and Crossref's polite pool is part of it.
    """
    out: Dict[str, str] = {}
    for k, v in (params or {}).items():
        lk = str(k).lower()
        if lk in SECRET_PARAMS:
            continue
        if lk in PRIVATE_PARAMS:
            out[str(k)] = "<redacted>"
            continue
        out[str(k)] = "" if v is None else str(v)
    return out


def request_key(url: str, params: Optional[dict] = None) -> str:
    """Stable identifier of one HTTP request, ignoring credentials.

    Replay matches archived responses on this key.  Excluding secrets and
    contact addresses is what makes an archive replayable by somebody who has
    neither: the reviewer's own ``mailto`` does not change the key, so the
    recorded response is still found.
    """
    filtered = {k: v for k, v in redact_params(params).items()
                if str(k).lower() not in PRIVATE_PARAMS}
    return _sha256(_canon([str(url).strip(), filtered]))


# ----------------------------------------------------------------------------
# record-level fingerprints
# ----------------------------------------------------------------------------
def _norm_journal(rec: Record) -> str:
    return normalize_title(rec.journal or "")


def checksum_payload(rec: Record) -> Dict[str, Any]:
    """The exact stable-field mapping that gets hashed for one record."""
    return {
        "doi": rec.doi or "",
        "pmid": rec.pmid or "",
        "openalex_id": rec.openalex_id or "",
        "scopus_id": rec.scopus_id or "",
        "norm_title": rec.norm_title,
        "year": rec.year if rec.year is not None else None,
        "norm_journal": _norm_journal(rec),
        "issn": (rec.issn or "").strip().upper(),
        "volume": _WS.sub(" ", str(rec.volume or "")).strip(),
        "issue": _WS.sub(" ", str(rec.issue or "")).strip(),
        "pages": _WS.sub(" ", str(rec.pages or "")).strip(),
        "doc_type": (rec.doc_type or "").strip().lower(),
        "language": (rec.language or "").strip().lower(),
        "first_author_surname": rec.first_author_surname,
        "n_authors": len(rec.authors or []),
        "has_abstract": bool((rec.abstract or "").strip()),
    }


def record_checksum(rec: Record) -> str:
    """SHA-256 over the stable bibliographic identity of one record."""
    return _sha256(_canon(checksum_payload(rec)))


def record_key(rec: Record) -> str:
    """Identity key used to align two harvests, strongest evidence first.

    The cascade mirrors :mod:`corpusslr.dedup`: a DOI is decisive, then PMID,
    then the provider's own record id, and only as a last resort the
    normalized title plus year.  Aligning on identity rather than on position
    is what lets :func:`compare_harvests` tell "record changed" from "record
    replaced".
    """
    if rec.doi:
        return "doi:" + rec.doi
    if rec.pmid:
        return "pmid:" + rec.pmid
    if rec.openalex_id:
        return "openalex:" + rec.openalex_id
    if rec.scopus_id:
        return "scopus:" + str(rec.scopus_id)
    if rec.source_id:
        return "sid:{}:{}".format(rec.source or "", rec.source_id)
    return "title:{}|{}".format(rec.norm_title, rec.year if rec.year else "")


def record_fingerprint(rec: Record) -> Dict[str, Any]:
    """Compact per-record entry stored in the manifest.

    Keeping identity, checksum and the volatile counters in the manifest means
    drift between two harvests can be audited from the two manifests alone -
    the reviewer does not need the full archives to answer "what changed?".
    """
    fp = {
        "key": record_key(rec),
        "checksum": record_checksum(rec),
        "doi": rec.doi or "",
        "title": _WS.sub(" ", rec.title or "").strip(),
        "year": rec.year,
        "source": rec.source or "",
        "source_id": rec.source_id or "",
    }
    for name in VOLATILE_FIELDS:
        fp[name] = getattr(rec, name, None)
    return fp


def sort_records(records: Iterable[Record]) -> List[Record]:
    """Return records in a canonical, relevance-independent order.

    Both supplementary APIs rank by proprietary relevance and neither
    guarantees a stable order across calls (measured: see
    ``reproducible_harvesting.md``).  Sorting by DOI, then normalized title,
    year and provider id makes the checksum, the CSV/RIS exports and every
    diff independent of that ranking.  Records without a DOI sort before
    records with one, so the boundary between "identifier-bearing" and
    "title-only" records is visible in any export.
    """
    return sorted(
        records,
        key=lambda r: (r.doi or "", r.norm_title,
                       r.year if r.year is not None else -1,
                       r.source or "", str(r.source_id or "")),
    )


def records_checksum(records: Sequence[Record]) -> str:
    """Order-independent checksum of a record set.

    Per-record checksums are sorted before hashing, so two harvests that
    retrieved the same studies in a different ranking produce the *same*
    value.  That is the property that makes the checksum usable as a corpus
    identifier in a paper.
    """
    return _sha256(_canon(sorted(record_checksum(r) for r in records)))


def record_diff_fields(a: Record, b: Record,
                       ignore: Sequence[str] = _ASSIGNED_FIELDS) -> List[str]:
    """Names of fields whose values differ between two records."""
    da, db = a.to_dict(), b.to_dict()
    skip = set(ignore)
    names = sorted(set(da) | set(db))
    return [n for n in names if n not in skip and da.get(n) != db.get(n)]


def records_equal(a: Sequence[Record], b: Sequence[Record],
                  ignore: Sequence[str] = _ASSIGNED_FIELDS) -> bool:
    """Field-by-field equality of two record sequences (not object identity).

    Used to verify a replay: the archived run and the live run must agree on
    every harmonized field.  Corpus-assigned bookkeeping (``uid``,
    ``search_id``, ``provenance``) is ignored because it is created at
    registration time, downstream of retrieval.
    """
    if len(a) != len(b):
        return False
    return all(not record_diff_fields(x, y, ignore=ignore)
               for x, y in zip(a, b))


# ----------------------------------------------------------------------------
# archived response objects
# ----------------------------------------------------------------------------
class ArchivedResponse:
    """Minimal ``requests.Response`` stand-in served from the archive."""

    def __init__(self, status_code: int, payload: Any = None, text: str = "",
                 headers: Optional[dict] = None, url: str = ""):
        self.status_code = int(status_code)
        self._payload = payload
        self.text = text if text is not None else ""
        self.headers = dict(headers or {})
        self.url = url
        self.content = self.text.encode("utf-8")

    def json(self):
        if self._payload is not None:
            return self._payload
        if not self.text:
            raise ValueError("archived response has no body")
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError("HTTP %d" % self.status_code)


def _payload_of(response) -> Any:
    try:
        return response.json()
    except Exception:                            # noqa: BLE001 - non-JSON body
        return None


def _api_version(payload: Any, headers: Optional[dict]) -> str:
    """Best-effort API version from a response body or headers.

    Crossref reports ``message-version`` in every payload; several other REST
    APIs use an ``X-Api-Version`` header.  Semantic Scholar's Graph API
    publishes neither, which is itself worth recording in the manifest.
    """
    if isinstance(payload, dict):
        for k in ("message-version", "apiVersion", "api_version", "version"):
            v = payload.get(k)
            if isinstance(v, (str, int, float)) and str(v).strip():
                return str(v).strip()
    for k, v in (headers or {}).items():
        if str(k).lower() in ("x-api-version", "api-version") and v:
            return str(v).strip()
    return ""


# ----------------------------------------------------------------------------
# manifest
# ----------------------------------------------------------------------------
@dataclass
class HarvestManifest:
    """Everything needed to cite, audit and repeat one harvest.

    The field set follows PRISMA-S items 1-8 (source, platform, interface,
    full strategy, filters, date, number of records) and adds the three items
    a purely narrative report cannot carry: the software version, the
    deterministic corpus checksum and the per-record fingerprint index used
    for drift detection.
    """

    harvest_id: str = "H1"
    database: str = ""
    platform: str = ""
    interface: str = "API"
    url: str = ""
    query: str = ""
    filters: str = ""
    compiled_params: Dict[str, Any] = field(default_factory=dict)
    max_results: Optional[int] = None
    package: str = "corpusslr"
    package_version: str = ""
    harvested_at: str = ""
    mode: str = "live"
    authenticated: bool = False
    api_version: str = ""
    n_responses: int = 0
    n_records: int = 0
    n_with_doi: int = 0
    checksum: str = ""
    checksum_algorithm: str = "sha256/canonical-json"
    checksum_fields: List[str] = field(default_factory=lambda: list(CHECKSUM_FIELDS))
    volatile_fields: List[str] = field(default_factory=lambda: list(VOLATILE_FIELDS))
    warnings: List[str] = field(default_factory=list)
    notes: str = ""
    record_index: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "harvest_id": self.harvest_id, "database": self.database,
            "platform": self.platform, "interface": self.interface,
            "url": self.url, "query": self.query, "filters": self.filters,
            "compiled_params": dict(self.compiled_params),
            "max_results": self.max_results, "package": self.package,
            "package_version": self.package_version,
            "harvested_at": self.harvested_at, "mode": self.mode,
            "authenticated": self.authenticated,
            "api_version": self.api_version,
            "n_responses": self.n_responses, "n_records": self.n_records,
            "n_with_doi": self.n_with_doi, "checksum": self.checksum,
            "checksum_algorithm": self.checksum_algorithm,
            "checksum_fields": list(self.checksum_fields),
            "volatile_fields": list(self.volatile_fields),
            "warnings": list(self.warnings), "notes": self.notes,
            "record_index": list(self.record_index),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HarvestManifest":
        d = dict(d or {})
        known = set(cls.__dataclass_fields__)              # noqa: SLF001
        return cls(**{k: v for k, v in d.items() if k in known})

    # ------------------------------------------------------------------
    def to_markdown(self) -> str:
        """Reproducibility statement for a methods section or appendix."""
        rows = [
            ("Database", self.database),
            ("Platform", self.platform),
            ("Interface", self.interface),
            ("Endpoint", self.url),
            ("Query as sent", self.query),
            ("Filters", self.filters or "-"),
            ("Date of harvest (UTC)", self.harvested_at),
            ("Software", "{} {}".format(self.package, self.package_version)),
            ("API version", self.api_version or "not published by the API"),
            ("Authenticated", "yes" if self.authenticated else "no (open access)"),
            ("HTTP responses archived", str(self.n_responses)),
            ("Records retrieved", str(self.n_records)),
            ("Records with DOI", "{} ({:.1f}%)".format(
                self.n_with_doi,
                100.0 * self.n_with_doi / self.n_records if self.n_records else 0.0)),
            ("Corpus checksum", "`{}`".format(self.checksum)),
            ("Checksum method", "{} over {}".format(
                self.checksum_algorithm, ", ".join(self.checksum_fields))),
        ]
        out = ["| Item | Value |", "|---|---|"]
        out += ["| {} | {} |".format(k, v) for k, v in rows]
        if self.warnings:
            out.append("")
            out.append("Compilation warnings carried into PRISMA-S:")
            out += ["- " + w for w in self.warnings]
        return "\n".join(out)


# ----------------------------------------------------------------------------
# archive
# ----------------------------------------------------------------------------
class HarvestArchive:
    """Directory of raw API responses plus a ``manifest.json`` index.

    This is the evidence base of an API-native review.  Every response is
    stored verbatim (parsed JSON when the body is JSON, raw text otherwise)
    together with the request that produced it, the HTTP status, a UTC
    timestamp and a checksum of the stored body, so a reader can verify that
    the archive was not edited after the fact.  Layout::

        archive/
          manifest.json          # harvests + response index
          responses/000001.json  # one file per HTTP response

    One directory may hold several harvests (one per database); each response
    carries its ``harvest_id`` so replay serves only the matching subset.
    """

    RESPONSE_DIR = "responses"
    MANIFEST = "manifest.json"

    def __init__(self, path: str, mode: str = "read",
                 package_version: str = ""):
        if mode not in ("read", "write"):
            raise ValueError("mode must be 'read' or 'write'")
        self.path = str(path)
        self.mode = mode
        self.package_version = package_version
        self.created_at = _utcnow()
        self.archive_version = ARCHIVE_VERSION
        self._responses: List[Dict[str, Any]] = []
        self._harvests: List[Dict[str, Any]] = []
        self._cursor: Dict[Tuple[str, str], int] = {}
        if mode == "write":
            os.makedirs(os.path.join(self.path, self.RESPONSE_DIR),
                        exist_ok=True)
            if os.path.exists(self._manifest_path()):
                self._load()                      # append to an existing archive
                self.mode = "write"
        else:
            self._load()

    # ------------------------------------------------------------------
    @classmethod
    def create(cls, path: str, package_version: str = "") -> "HarvestArchive":
        """Open *path* for writing, creating it if needed."""
        return cls(path, mode="write", package_version=package_version)

    @classmethod
    def open(cls, path: str) -> "HarvestArchive":
        """Open an existing archive read-only (used for replay and audit)."""
        return cls(path, mode="read")

    # ------------------------------------------------------------------
    def _manifest_path(self) -> str:
        return os.path.join(self.path, self.MANIFEST)

    def _load(self) -> None:
        mpath = self._manifest_path()
        if not os.path.isfile(mpath):
            raise HarvestError(
                "no {} in {!r}: not a CorpusSLR harvest archive".format(
                    self.MANIFEST, self.path))
        try:
            with open(mpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except ValueError as exc:
            raise HarvestError("{} is not valid JSON: {}".format(mpath, exc))
        if not isinstance(data, dict):
            raise HarvestError("{}: manifest must be a JSON object".format(mpath))
        ver = data.get("archive_version")
        if isinstance(ver, int) and ver > ARCHIVE_VERSION:
            raise HarvestError(
                "archive_version {} is newer than this corpusslr understands "
                "({}); upgrade the package to replay it".format(
                    ver, ARCHIVE_VERSION))
        self.archive_version = ver if isinstance(ver, int) else ARCHIVE_VERSION
        self.created_at = data.get("created_at") or self.created_at
        self.package_version = (self.package_version
                                or data.get("package_version") or "")
        self._responses = list(data.get("responses") or [])
        self._harvests = list(data.get("harvests") or [])

    # ------------------------------------------------------------------
    @property
    def harvests(self) -> List[HarvestManifest]:
        return [HarvestManifest.from_dict(h) for h in self._harvests]

    def harvest_ids(self) -> List[str]:
        return [str(h.get("harvest_id") or "") for h in self._harvests]

    def manifest(self, harvest_id: Optional[str] = None) -> HarvestManifest:
        """Return one harvest manifest; the only one if *harvest_id* is None."""
        if not self._harvests:
            raise HarvestError(
                "archive {!r} contains no harvest manifest".format(self.path))
        if harvest_id is None:
            if len(self._harvests) > 1:
                raise HarvestError(
                    "archive {!r} holds {} harvests ({}); pass harvest_id".format(
                        self.path, len(self._harvests),
                        ", ".join(self.harvest_ids())))
            return HarvestManifest.from_dict(self._harvests[0])
        for h in self._harvests:
            if str(h.get("harvest_id")) == str(harvest_id):
                return HarvestManifest.from_dict(h)
        raise HarvestError("no harvest {!r} in {!r} (have: {})".format(
            harvest_id, self.path, ", ".join(self.harvest_ids()) or "none"))

    def resolve_harvest_id(self, database: str = "") -> Optional[str]:
        """Pick the harvest to replay: the only one, or the one for *database*."""
        if not self._harvests:
            raise HarvestError(
                "archive {!r} contains no harvest manifest".format(self.path))
        if len(self._harvests) == 1:
            return str(self._harvests[0].get("harvest_id"))
        hits = [str(h.get("harvest_id")) for h in self._harvests
                if str(h.get("database", "")).lower() == str(database).lower()]
        if len(hits) == 1:
            return hits[0]
        raise HarvestError(
            "archive {!r} holds {} harvests ({}); pass harvest_id "
            "explicitly".format(self.path, len(self._harvests),
                                ", ".join(self.harvest_ids())))

    # ------------------------------------------------------------------
    def add_response(self, url: str, params: Optional[dict],
                     status_code: int, text: str = "", payload: Any = None,
                     headers: Optional[dict] = None,
                     harvest_id: str = "H1",
                     authenticated: bool = False) -> Dict[str, Any]:
        """Write one HTTP response to disk and index it.

        The stored body is the parsed JSON when the response is JSON, so the
        archive stays readable and diffable; ``content_sha256`` is taken over
        the canonical serialization of exactly what was stored, and
        ``wire_sha256`` over the bytes as received, so both "did the file
        change?" and "did the file match the wire?" can be answered.
        """
        if self.mode != "write":
            raise HarvestError("archive opened read-only")
        seq = len(self._responses) + 1
        rel = os.path.join(self.RESPONSE_DIR, "%06d.json" % seq)
        kept = {k: v for k, v in (headers or {}).items()
                if str(k).lower() in _KEPT_HEADERS}
        if payload is not None:
            body_repr, stored = "json", _canon(payload)
        else:
            body_repr, stored = "text", (text or "")
        entry = {
            "seq": seq,
            "harvest_id": harvest_id,
            "file": rel.replace(os.sep, "/"),
            "url": str(url),
            "params": redact_params(params),
            "request_key": request_key(url, params),
            "status": int(status_code),
            "retrieved_at": _utcnow(),
            "body_repr": body_repr,
            "content_sha256": _sha256(stored),
            "wire_sha256": _sha256(text or ""),
            "content_length": len(stored),
            "authenticated": bool(authenticated),
            "api_version": _api_version(payload, headers),
        }
        doc = dict(entry)
        doc["response_headers"] = kept
        if payload is not None:
            doc["body"] = payload
        else:
            doc["body_text"] = text or ""
        with open(os.path.join(self.path, rel), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        self._responses.append(entry)
        return entry

    def add_harvest(self, manifest: HarvestManifest) -> None:
        """Register (or replace) a harvest manifest in this archive."""
        if self.mode != "write":
            raise HarvestError("archive opened read-only")
        d = manifest.to_dict()
        for i, h in enumerate(self._harvests):
            if str(h.get("harvest_id")) == str(manifest.harvest_id):
                self._harvests[i] = d
                break
        else:
            self._harvests.append(d)

    def next_harvest_id(self) -> str:
        used = set(self.harvest_ids())
        i = len(used) + 1
        while "H%d" % i in used:
            i += 1
        return "H%d" % i

    def write_manifest(self) -> str:
        """Serialize the manifest; returns its path."""
        if self.mode != "write":
            raise HarvestError("archive opened read-only")
        doc = {
            "archive_version": ARCHIVE_VERSION,
            "package": "corpusslr",
            "package_version": self.package_version,
            "created_at": self.created_at,
            "written_at": _utcnow(),
            "n_harvests": len(self._harvests),
            "n_responses": len(self._responses),
            "harvests": self._harvests,
            "responses": self._responses,
        }
        path = self._manifest_path()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        return path

    # ------------------------------------------------------------------
    def response_index(self, harvest_id: Optional[str] = None
                       ) -> List[Dict[str, Any]]:
        if harvest_id is None:
            return list(self._responses)
        return [e for e in self._responses
                if str(e.get("harvest_id")) == str(harvest_id)]

    def load_response(self, entry: Dict[str, Any],
                      verify: bool = True) -> ArchivedResponse:
        """Materialize one archived response, checking its checksum."""
        rel = str(entry.get("file") or "")
        full = os.path.join(self.path, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            raise HarvestError(
                "archive incomplete: response file {!r} (seq {}) is "
                "missing".format(rel, entry.get("seq")))
        try:
            with open(full, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except ValueError as exc:
            raise HarvestError("{}: corrupted JSON ({})".format(rel, exc))
        if "body" in doc:
            payload, text = doc["body"], _canon(doc["body"])
        else:
            payload, text = None, doc.get("body_text") or ""
        if verify:
            got = _sha256(text)
            want = str(entry.get("content_sha256") or "")
            if want and got != want:
                raise HarvestError(
                    "archive tampered or corrupted: {} checksum {} != "
                    "manifest {}".format(rel, got[:12], want[:12]))
        return ArchivedResponse(int(doc.get("status", entry.get("status", 200))),
                                payload=payload, text=text,
                                headers=doc.get("response_headers") or {},
                                url=str(doc.get("url") or ""))

    # ------------------------------------------------------------------
    def verify(self, harvest_id: Optional[str] = None) -> List[str]:
        """Integrity audit; returns a list of human-readable problems.

        An empty list is the statement a reviewer needs: every indexed
        response file exists, parses, and hashes to the value recorded in the
        manifest, the sequence has no gaps, and every harvest's response count
        matches its manifest.
        """
        problems: List[str] = []
        if not self._harvests:
            problems.append("manifest lists no harvests")
        entries = self.response_index(harvest_id)
        if not entries:
            problems.append("manifest lists no responses"
                            + (" for harvest %s" % harvest_id if harvest_id else ""))
        seqs = [int(e.get("seq") or 0) for e in self.response_index()]
        if seqs and sorted(seqs) != list(range(1, len(seqs) + 1)):
            problems.append("response sequence has gaps or duplicates: %s"
                            % sorted(seqs))
        for e in entries:
            try:
                self.load_response(e, verify=True)
            except HarvestError as exc:
                problems.append(str(exc))
        for h in self._harvests:
            hid = str(h.get("harvest_id"))
            if harvest_id is not None and hid != str(harvest_id):
                continue
            n_idx = len(self.response_index(hid))
            n_man = int(h.get("n_responses") or 0)
            if n_man and n_man != n_idx:
                problems.append(
                    "harvest {}: manifest claims {} responses, archive holds "
                    "{}".format(hid, n_man, n_idx))
        return problems


# ----------------------------------------------------------------------------
# sessions
# ----------------------------------------------------------------------------
class RecordingSession:
    """``requests.Session`` proxy that archives every response it forwards.

    Wrapping the session rather than the client keeps every existing source
    class untouched: politeness intervals, retry-on-429 and cursor paging all
    run exactly as in a normal search, and the archive receives the failed
    attempts too, which is what makes a rate-limit incident auditable.
    """

    def __init__(self, archive: HarvestArchive, session=None,
                 harvest_id: str = "H1"):
        if session is None:
            import requests
            session = requests.Session()
        self.session = session
        self.archive = archive
        self.harvest_id = harvest_id
        self.calls: List[Dict[str, Any]] = []

    # `BaseSource.__init__` and callers mutate `.headers`; proxy it through.
    @property
    def headers(self):
        return self.session.headers

    @headers.setter
    def headers(self, value):
        self.session.headers = value

    def __getattr__(self, name):                  # pragma: no cover - proxy
        return getattr(self.session, name)

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        r = self.session.get(url, params=params, headers=headers,
                             timeout=timeout, **kw)
        authed = any(str(k).lower() in SECRET_PARAMS
                     for k in list((headers or {}).keys())
                     + list((params or {}).keys()))
        self.calls.append({"url": url, "params": dict(params or {})})
        self.archive.add_response(
            url, params, getattr(r, "status_code", 0),
            text=getattr(r, "text", "") or "", payload=_payload_of(r),
            headers=dict(getattr(r, "headers", {}) or {}),
            harvest_id=self.harvest_id, authenticated=authed)
        return r


class ReplaySession:
    """Offline ``requests.Session`` stand-in served from a :class:`HarvestArchive`.

    Responses are matched on :func:`request_key`, i.e. on endpoint plus
    non-secret parameters, and consumed in recorded order, so cursor and
    offset paging replay along the identical path.  Transient failures (429,
    5xx) that the live run retried past are skipped by default: they are
    preserved in the archive as evidence, but re-serving them would only make
    the replay sleep through the same backoff.  No socket is opened - the
    class has no HTTP machinery at all, which is the guarantee a reviewer
    without database access needs.
    """

    def __init__(self, archive: HarvestArchive, harvest_id: Optional[str] = None,
                 verify: bool = True, skip_transient: bool = True):
        self.archive = archive
        self.harvest_id = harvest_id
        self.verify = verify
        self.skip_transient = skip_transient
        self.headers: Dict[str, str] = {}
        self.calls: List[Dict[str, Any]] = []
        self._by_key: Dict[str, List[Dict[str, Any]]] = {}
        for e in archive.response_index(harvest_id):
            self._by_key.setdefault(str(e.get("request_key")), []).append(e)
        self._used: Dict[str, int] = {}
        self.served = 0

    def _next_entry(self, key: str) -> Dict[str, Any]:
        queue = self._by_key.get(key) or []
        i = self._used.get(key, 0)
        while i < len(queue):
            e = queue[i]
            i += 1
            status = int(e.get("status") or 0)
            if self.skip_transient and (status == 429 or status >= 500):
                continue
            self._used[key] = i
            return e
        self._used[key] = i
        raise HarvestError(
            "no archived response left for this request (key {}...); the "
            "archive is incomplete or the query does not match the recorded "
            "one".format(key[:12]))

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        key = request_key(url, params)
        self.calls.append({"url": url, "params": dict(params or {}),
                           "request_key": key})
        entry = self._next_entry(key)
        self.served += 1
        return self.archive.load_response(entry, verify=self.verify)


# ----------------------------------------------------------------------------
# harvesting
# ----------------------------------------------------------------------------
@dataclass
class HarvestResult:
    """Records in canonical order plus the provenance needed to publish them."""

    records: List[Record] = field(default_factory=list)
    event: Optional[SearchEvent] = None
    manifest: Optional[HarvestManifest] = None
    archive_path: str = ""
    mode: str = "live"
    #: Only meaningful after a replay: does the recomputed corpus checksum
    #: equal the one recorded at harvest time?
    checksum_matches: Optional[bool] = None
    recorded_checksum: str = ""

    @property
    def checksum(self) -> str:
        return self.manifest.checksum if self.manifest else ""

    def to_source_result(self) -> SourceResult:
        """Adapt to the package-wide return type for ``Corpus.add_search``.

        A harvest that produced no search event never reached the API, so it
        cannot be registered as a search: raising here keeps an incomplete
        harvest out of the PRISMA counts instead of contributing a blank row.
        """
        if self.event is None:
            raise HarvestError(
                "harvest carries no search event, so it cannot be added to a "
                "corpus; inspect .records directly or re-run the harvest")
        return SourceResult(event=self.event, records=list(self.records))

    def write_manifest(self, path: str) -> str:
        """Write the standalone manifest JSON (for a data-availability deposit)."""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.manifest.to_dict() if self.manifest else {}, fh,
                      ensure_ascii=False, indent=1, sort_keys=True)
        return path

    def __len__(self) -> int:
        return len(self.records)


def _query_repr(source, query) -> Tuple[str, str, Dict[str, Any]]:
    """Human-readable query, filters and the compiled parameter mapping."""
    name = getattr(source, "name", "")
    try:
        if name == "Crossref":
            params = dict(query.to_crossref_params())
            return (str(params.get("query.bibliographic", "")),
                    str(params.get("filter", "")), params)
        if name == "Semantic Scholar":
            params = dict(query.to_semanticscholar())
            filters = "; ".join(
                "{}={}".format(k, params[k])
                for k in ("year", "publicationTypes") if k in params)
            return str(params.get("query", "")), filters, params
        compiled = query.compile_all()
        return str(compiled.get(name.lower(), "")), "", {}
    except Exception:                             # noqa: BLE001 - never fatal
        return "", "", {}


def harvest(source, query, max_results: Optional[int] = None,
            archive=None, replay: bool = False,
            harvest_id: Optional[str] = None,
            package_version: str = "", notes: str = "",
            verify: bool = True, strict: bool = True) -> HarvestResult:
    """Run one reproducible harvest - live with archiving, or offline from archive.

    This single entry point is deliberately used for both directions, because
    "the reviewer runs a *different* function" is exactly the loophole that
    makes reproducibility claims untestable.  With ``replay=False`` the source
    executes normally and every HTTP response is written to *archive*; with
    ``replay=True`` the identical call is served from that archive with no
    network access, and the resulting record set is checked against the
    checksum recorded at harvest time.

    Parameters
    ----------
    source:
        Any :class:`~corpusslr.sources.base.BaseSource` instance.  Its session
        is temporarily swapped and restored afterwards, so the object is
        reusable.
    query:
        The :class:`~corpusslr.query.SearchQuery` to compile and run.
    max_results:
        Cap on retrieved records.  On replay, ``None`` reuses the cap recorded
        in the manifest, so the reviewer cannot silently widen the harvest.
    archive:
        A :class:`HarvestArchive`, or a path.  Required for replay; optional
        (but recommended) for a live harvest - without it the call still
        returns a manifest and a checksum, just no raw evidence.
    verify:
        Check every archived body against its manifest checksum while replaying.
    strict:
        Raise :class:`HarvestError` if the archive fails its integrity audit or
        the replayed checksum differs from the recorded one.  Set ``False`` to
        obtain the divergence in the result instead of an exception.

    Returns
    -------
    HarvestResult
        Records in canonical order, a PRISMA-S-ready
        :class:`~corpusslr.corpus.SearchEvent` and the
        :class:`HarvestManifest`.
    """
    from . import __version__ as _pkg_version

    pkg_version = package_version or _pkg_version
    own_archive = None
    if isinstance(archive, str):
        own_archive = (HarvestArchive.open(archive) if replay
                       else HarvestArchive.create(archive,
                                                  package_version=pkg_version))
        archive = own_archive
    if replay and archive is None:
        raise HarvestError("replay requires an archive")

    recorded: Optional[HarvestManifest] = None
    if replay:
        hid = harvest_id or archive.resolve_harvest_id(
            getattr(source, "name", ""))
        problems = archive.verify(hid)
        if problems and strict:
            raise HarvestError("archive {!r} failed verification: {}".format(
                archive.path, "; ".join(problems[:5])))
        recorded = archive.manifest(hid)
        if recorded.mode == "aborted" and strict:
            raise HarvestError(
                "harvest {} in {!r} was aborted before completion ({}); it is "
                "not a reproducible record set - re-run the live harvest or "
                "pass strict=False to inspect the partial evidence".format(
                    hid, archive.path, recorded.notes or "no note"))
        if max_results is None:
            max_results = recorded.max_results
        session: Optional[Union[ReplaySession, RecordingSession]] = \
            ReplaySession(archive, harvest_id=hid, verify=verify)
    else:
        hid = harvest_id or (archive.next_harvest_id() if archive else "H1")
        session = (RecordingSession(archive, source.session, harvest_id=hid)
                   if archive is not None else None)

    if max_results is None:
        max_results = DEFAULT_MAX_RESULTS

    saved_session = source.session
    saved_interval = getattr(source, "min_interval", None)
    started = _utcnow()
    try:
        if session is not None:
            source.session = session
        if replay:
            # Politeness intervals exist to protect a live API; replaying an
            # archive must not sleep.
            source.min_interval = 0.0
            source._last = 0.0
        result = source.search(query, max_results=max_results)
    except BaseException as exc:
        # A harvest that dies half-way (exhausted 429 retries, network loss,
        # Ctrl-C) has already written response files.  Without a manifest they
        # are unindexed and unverifiable, so the partial archive is closed with
        # an explicit ``aborted`` harvest entry: the failed attempts stay
        # available as evidence of what the API answered, and
        # :meth:`HarvestArchive.verify` still passes on the directory.
        if not replay and archive is not None:
            n_partial = len(archive.response_index(hid))
            archive.add_harvest(HarvestManifest(
                harvest_id=hid,
                database=getattr(source, "name", ""),
                platform=getattr(source, "platform", ""),
                url="", query="", max_results=max_results,
                package_version=pkg_version,
                harvested_at=started, mode="aborted",
                authenticated=bool(getattr(source, "api_key", "")
                                   or getattr(source, "insttoken", "")),
                n_responses=n_partial, n_records=0,
                warnings=list(getattr(query, "warnings", []) or []),
                notes="harvest aborted after {} response(s): {}: {}".format(
                    n_partial, type(exc).__name__, str(exc)[:300])))
            archive.write_manifest()
        raise
    finally:
        source.session = saved_session
        if saved_interval is not None:
            source.min_interval = saved_interval

    records = sort_records(result.records)
    checksum = records_checksum(records)
    q, filters, params = _query_repr(source, query)
    ev = result.event
    n_responses = getattr(session, "served", None)
    if n_responses is None:
        n_responses = len(getattr(session, "calls", []) or [])
    authed = bool(getattr(source, "api_key", "") or
                  getattr(source, "insttoken", ""))
    api_ver = ""
    if archive is not None:
        for e in archive.response_index(hid):
            if e.get("api_version"):
                api_ver = str(e["api_version"])
                break
    if not api_ver and recorded is not None:
        api_ver = recorded.api_version

    manifest = HarvestManifest(
        harvest_id=hid,
        database=getattr(ev, "database", "") or getattr(source, "name", ""),
        platform=getattr(ev, "platform", "") or getattr(source, "platform", ""),
        interface=getattr(ev, "interface", "API"),
        url=getattr(ev, "url", ""),
        query=q or getattr(ev, "query", ""),
        filters=filters or getattr(ev, "filters", ""),
        compiled_params=params,
        max_results=max_results,
        package_version=pkg_version,
        harvested_at=(recorded.harvested_at if replay and recorded
                      else started),
        mode="replay" if replay else "live",
        authenticated=authed,
        api_version=api_ver,
        n_responses=int(n_responses),
        n_records=len(records),
        n_with_doi=sum(1 for r in records if r.doi),
        checksum=checksum,
        warnings=list(getattr(query, "warnings", []) or []),
        notes=notes or getattr(ev, "notes", ""),
        record_index=[record_fingerprint(r) for r in records],
    )

    if ev is not None:
        ev.records_retrieved = len(records)
        trail = ("harvest_id={}; corpus checksum sha256={}; archive={}"
                 .format(hid, checksum,
                         archive.path if archive is not None else "none"))
        ev.notes = (ev.notes + "; " + trail) if ev.notes else trail

    matches: Optional[bool] = None
    if replay and recorded is not None:
        matches = (checksum == recorded.checksum)
        if not matches and strict:
            raise HarvestError(
                "replay diverged: recomputed checksum {} != recorded {} "
                "({} vs {} records)".format(
                    checksum[:12], (recorded.checksum or "")[:12],
                    len(records), recorded.n_records))
    if not replay and archive is not None:
        archive.add_harvest(manifest)
        archive.write_manifest()

    return HarvestResult(
        records=records, event=ev, manifest=manifest,
        archive_path=archive.path if archive is not None else "",
        mode="replay" if replay else "live",
        checksum_matches=matches,
        recorded_checksum=recorded.checksum if recorded else "")


def replay_harvest(source, query, archive, **kw) -> HarvestResult:
    """Convenience wrapper: :func:`harvest` with ``replay=True``."""
    kw.pop("replay", None)
    return harvest(source, query, archive=archive, replay=True, **kw)


def verify_archive(archive, harvest_id: Optional[str] = None) -> List[str]:
    """Integrity audit of an archive given as a path or object."""
    arc = HarvestArchive.open(archive) if isinstance(archive, str) else archive
    return arc.verify(harvest_id)


# ----------------------------------------------------------------------------
# drift
# ----------------------------------------------------------------------------
@dataclass
class HarvestDiff:
    """Explicit, countable difference between two harvests of one query."""

    added: List[Dict[str, Any]] = field(default_factory=list)
    removed: List[Dict[str, Any]] = field(default_factory=list)
    changed: List[Dict[str, Any]] = field(default_factory=list)
    citation_updates: List[Dict[str, Any]] = field(default_factory=list)
    unchanged: int = 0
    n_before: int = 0
    n_after: int = 0
    checksum_before: str = ""
    checksum_after: str = ""
    label_before: str = "before"
    label_after: str = "after"

    @property
    def stable(self) -> bool:
        """True when nothing but volatile counters differs."""
        return not (self.added or self.removed or self.changed)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_before": self.n_before, "n_after": self.n_after,
            "checksum_before": self.checksum_before,
            "checksum_after": self.checksum_after,
            "n_added": len(self.added), "n_removed": len(self.removed),
            "n_changed": len(self.changed), "unchanged": self.unchanged,
            "n_citation_updates": len(self.citation_updates),
            "stable": self.stable,
            "added": self.added, "removed": self.removed,
            "changed": self.changed,
            "citation_updates": self.citation_updates,
        }

    def summary(self) -> str:
        return ("Harvest drift {} -> {}: {} -> {} records; "
                "+{} added, -{} removed, {} changed, {} unchanged, "
                "{} citation-count updates; checksum {} -> {}".format(
                    self.label_before, self.label_after,
                    self.n_before, self.n_after, len(self.added),
                    len(self.removed), len(self.changed), self.unchanged,
                    len(self.citation_updates),
                    (self.checksum_before or "?")[:12],
                    (self.checksum_after or "?")[:12]))

    def to_markdown(self, limit: int = 20) -> str:
        """Drift table for a PRISMA-S appendix or a revision cover letter."""
        out = ["| Change | Records |", "|---|---|",
               "| Present in both, identical | {} |".format(self.unchanged),
               "| Added | {} |".format(len(self.added)),
               "| Removed | {} |".format(len(self.removed)),
               "| Metadata changed | {} |".format(len(self.changed)),
               "| Citation count updated only | {} |".format(
                   len(self.citation_updates))]
        for title, rows in (("Added", self.added), ("Removed", self.removed)):
            if not rows:
                continue
            out += ["", "**{}**".format(title), ""]
            for r in rows[:limit]:
                out.append("- {} ({}) {}".format(
                    r.get("doi") or r.get("key"), r.get("year") or "n.d.",
                    (r.get("title") or "")[:120]))
            if len(rows) > limit:
                out.append("- ... and {} more".format(len(rows) - limit))
        if self.changed:
            out += ["", "**Metadata changed**", ""]
            for c in self.changed[:limit]:
                out.append("- {}: {}".format(
                    c.get("key"), ", ".join(c.get("fields") or []) or "checksum"))
            if len(self.changed) > limit:
                out.append("- ... and {} more".format(len(self.changed) - limit))
        return "\n".join(out)


def _fingerprints(obj) -> Tuple[List[Dict[str, Any]], str, str]:
    """Normalize a harvest, manifest, archive path or record list to fingerprints."""
    if isinstance(obj, HarvestResult):
        return (list(obj.manifest.record_index) if obj.manifest
                else [record_fingerprint(r) for r in obj.records],
                obj.checksum, obj.manifest.harvested_at if obj.manifest else "")
    if isinstance(obj, HarvestManifest):
        return list(obj.record_index), obj.checksum, obj.harvested_at
    if isinstance(obj, HarvestArchive):
        m = obj.manifest()
        return list(m.record_index), m.checksum, m.harvested_at
    if isinstance(obj, str):
        if os.path.isdir(obj):
            m = HarvestArchive.open(obj).manifest()
        else:
            with open(obj, "r", encoding="utf-8") as fh:
                m = HarvestManifest.from_dict(json.load(fh))
        return list(m.record_index), m.checksum, m.harvested_at
    if isinstance(obj, dict):
        m = HarvestManifest.from_dict(obj)
        return list(m.record_index), m.checksum, m.harvested_at
    records = list(obj)
    if records and not isinstance(records[0], Record):
        raise TypeError("cannot compare objects of type %s"
                        % type(records[0]).__name__)
    return ([record_fingerprint(r) for r in records],
            records_checksum(records), "")


def compare_harvests(before, after, label_before: str = "",
                     label_after: str = "") -> HarvestDiff:
    """Quantify the drift between two harvests of the same query.

    Bibliographic databases are append-mostly and self-correcting, so a
    re-run months later *will* differ.  A systematic review can live with
    that, but only if the difference is stated: this function aligns the two
    harvests on record identity (:func:`record_key`) and reports records
    added, removed and changed, keeping pure citation-count updates in a
    separate bucket so that growth in a counter is never reported as
    instability of the search.

    Both arguments may be a :class:`HarvestResult`, a
    :class:`HarvestManifest`, a manifest ``dict``, an archive directory or
    manifest path, or simply a list of :class:`~corpusslr.record.Record` -
    a reviewer can therefore diff two deposited manifests without re-running
    anything.
    """
    fa, ca, da = _fingerprints(before)
    fb, cb, db = _fingerprints(after)
    idx_a: Dict[str, Dict[str, Any]] = {}
    for f in fa:
        idx_a.setdefault(str(f.get("key")), f)
    idx_b: Dict[str, Dict[str, Any]] = {}
    for f in fb:
        idx_b.setdefault(str(f.get("key")), f)

    added = [idx_b[k] for k in sorted(set(idx_b) - set(idx_a))]
    removed = [idx_a[k] for k in sorted(set(idx_a) - set(idx_b))]
    changed: List[Dict[str, Any]] = []
    cites: List[Dict[str, Any]] = []
    unchanged = 0
    for k in sorted(set(idx_a) & set(idx_b)):
        x, y = idx_a[k], idx_b[k]
        if x.get("checksum") != y.get("checksum"):
            fields = sorted(n for n in set(x) | set(y)
                            if n not in ("checksum",) + VOLATILE_FIELDS
                            and x.get(n) != y.get(n))
            changed.append({"key": k, "doi": y.get("doi", ""),
                            "title": y.get("title", ""), "fields": fields,
                            "checksum_before": x.get("checksum", ""),
                            "checksum_after": y.get("checksum", "")})
            continue
        vol = [n for n in VOLATILE_FIELDS if x.get(n) != y.get(n)]
        if vol:
            cites.append({"key": k, "doi": y.get("doi", ""),
                          "fields": vol,
                          "before": {n: x.get(n) for n in vol},
                          "after": {n: y.get(n) for n in vol}})
        unchanged += 1
    return HarvestDiff(
        added=added, removed=removed, changed=changed, citation_updates=cites,
        unchanged=unchanged, n_before=len(fa), n_after=len(fb),
        checksum_before=ca, checksum_after=cb,
        label_before=label_before or da or "before",
        label_after=label_after or db or "after")


def harvest_markdown(results: Sequence[HarvestResult]) -> str:
    """Reproducibility appendix for one or more harvests."""
    out = ["## Reproducible harvesting", ""]
    for r in results:
        m = r.manifest
        if m is None:
            continue
        out += ["### {} ({})".format(m.database, m.harvested_at), "",
                m.to_markdown(), ""]
        if r.archive_path:
            out += ["Raw responses archived in `{}`; replay with "
                    "`harvest(source, query, archive='{}', replay=True)`."
                    .format(r.archive_path, r.archive_path), ""]
    return "\n".join(out)
