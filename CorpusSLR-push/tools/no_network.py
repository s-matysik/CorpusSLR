"""Pytest plugin that turns any outbound network call into a test failure.

CorpusSLR retrieves records from remote bibliographic APIs, so the claim that
its test suite runs fully offline is one a reviewer is entitled to see enforced
rather than asserted. Loading this plugin (``pytest -p tools.no_network``)
replaces the connect primitives of the standard library with raising stubs
before collection starts. A test that reaches the network then fails with a
message naming the address it tried to open, instead of passing on a developer
machine that happens to be online and hanging in continuous integration.

The plugin patches ``socket`` rather than ``requests`` on purpose: patching the
HTTP client would leave ``urllib``, ``http.client`` and any transitive
dependency free to open a connection, and it is precisely those indirect paths
that make an accidentally networked test hard to notice.

Local inter-process sockets remain usable, because pytest's own machinery and
several standard-library helpers rely on them and they cannot leave the host.
"""

from __future__ import annotations

import socket

#: Address families that cannot reach another host and are therefore left
#: alone. ``AF_UNIX`` is absent on some platforms, hence the guarded lookup.
_LOCAL_FAMILIES = frozenset(
    f for f in (getattr(socket, "AF_UNIX", None),) if f is not None
)

_REMEDY = (
    "all CorpusSLR tests must run offline against the HTTP doubles in "
    "tests/conftest.py (FakeSession / FakeResponse)"
)


class NetworkUseInTestSuite(RuntimeError):
    """Raised when a test attempts to open a network connection."""


_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REAL_CREATE_CONNECTION = socket.create_connection


def _guarded_connect(self, address, *args, **kwargs):
    if getattr(self, "family", None) in _LOCAL_FAMILIES:
        return _REAL_CONNECT(self, address, *args, **kwargs)
    raise NetworkUseInTestSuite(
        "socket.connect({0!r}) blocked: {1}".format(address, _REMEDY)
    )


def _guarded_connect_ex(self, address, *args, **kwargs):
    if getattr(self, "family", None) in _LOCAL_FAMILIES:
        return _REAL_CONNECT_EX(self, address, *args, **kwargs)
    raise NetworkUseInTestSuite(
        "socket.connect_ex({0!r}) blocked: {1}".format(address, _REMEDY)
    )


def _guarded_create_connection(address, *args, **kwargs):
    raise NetworkUseInTestSuite(
        "socket.create_connection({0!r}) blocked: {1}".format(address, _REMEDY)
    )


def pytest_configure(config):
    """Install the guards before any test module is imported."""
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.create_connection = _guarded_create_connection


def pytest_unconfigure(config):
    """Restore the standard library, so an interactive session stays usable."""
    socket.socket.connect = _REAL_CONNECT
    socket.socket.connect_ex = _REAL_CONNECT_EX
    socket.create_connection = _REAL_CREATE_CONNECTION
