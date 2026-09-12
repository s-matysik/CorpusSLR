"""Offline HTTP harness: a fake requests.Session recording calls and
replaying scripted responses. No network is touched by any test."""
import json as _json
from typing import Any, List

import pytest


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else (
            _json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        import requests
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Replays a list of responses (or a callable(url, params, headers))."""

    def __init__(self, responses: Any):
        self.headers = {}
        self.calls: List[dict] = []
        self._responses = responses

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.calls.append({"url": url, "params": dict(params or {}),
                           "headers": dict(headers or {})})
        r = self._responses
        if callable(r):
            return r(url, params or {}, headers or {})
        if isinstance(r, list):
            if not r:
                raise AssertionError("FakeSession: ran out of responses")
            return r.pop(0)
        return r


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Kill throttling/backoff sleeps so retry paths run instantly."""
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
