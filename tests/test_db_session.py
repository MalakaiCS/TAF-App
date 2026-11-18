"""The database session survives a working day: an expired sign-in token is
renewed and the request sent again, a stale connection is retried - and a
write that may already have arrived is never sent twice."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx                                                 # noqa: E402
from postgrest.base_request_builder import RequestConfig     # noqa: E402

from taf_order_app import db_session as ds                   # noqa: E402


class _Session:
    def __init__(self, token, life):
        self.access_token = token
        self.refresh_token = "r-" + token
        self.expires_at = time.time() + life


class _Auth:
    """Enough of the auth client: a stored session, and a renewal that
    hands out the next token and tells the client, as the library does."""
    _persist_session = False

    def __init__(self, client, life):
        self.client = client
        self.n = 0
        self._in_memory_session = _Session("t0", life)
        self.refreshed = 0
        self.fail = False

    def refresh_session(self, refresh_token=None):
        if self.fail:
            raise RuntimeError("offline")
        self.n += 1
        self.refreshed += 1
        self._in_memory_session = _Session(f"t{self.n}", 3600)
        self.client.options.headers["Authorization"] = f"Bearer t{self.n}"


class _Client:
    def __init__(self, life):
        self.options = type("O", (), {})()
        self.options.headers = {"Authorization": "Bearer t0"}
        self.auth = _Auth(self, life)


def _setup(handler, life=3600, signed_in=True):
    client = _Client(life)
    ds._last_failed = 0.0
    ds.install(lambda: client, lambda: signed_in)
    session = httpx.Client(transport=httpx.MockTransport(handler))
    return client, session


def _request(session, method="GET", token="t0"):
    return RequestConfig(session, httpx.URL("https://db.example/rest/v1/orders"),
                         method, httpx.Headers({"Authorization":
                                                f"Bearer {token}"}),
                         httpx.QueryParams(), None, {"a": 1})


def test_an_expired_token_is_renewed_and_the_request_sent_again():
    seen = []

    def handler(req):
        seen.append(req.headers["Authorization"])
        if req.headers["Authorization"] == "Bearer t0":
            return httpx.Response(401, json={"code": "PGRST301",
                                             "message": "JWT expired"})
        return httpx.Response(200, json=[{"id": 1}])
    client, session = _setup(handler)
    resp = _request(session).send(httpx.Headers())
    assert resp.status_code == 200
    assert seen == ["Bearer t0", "Bearer t1"] and client.auth.refreshed == 1


def test_a_token_about_to_run_out_is_renewed_first():
    seen = []

    def handler(req):
        seen.append(req.headers["Authorization"])
        return httpx.Response(200, json=[])
    client, session = _setup(handler, life=60)
    assert _request(session).send(httpx.Headers()).status_code == 200
    assert seen == ["Bearer t1"] and client.auth.refreshed == 1


def test_a_stale_connection_is_retried_reads_and_writes():
    for method in ("GET", "POST"):
        calls = []

        def handler(req):
            calls.append(1)
            if len(calls) == 1:
                raise httpx.RemoteProtocolError("Server disconnected")
            return httpx.Response(201, json=[])
        _client, session = _setup(handler)
        assert _request(session, method).send(httpx.Headers()).status_code \
            == 201
        assert len(calls) == 2, method


def test_a_write_that_may_have_arrived_is_not_sent_twice():
    calls = []

    def handler(req):
        calls.append(req.method)
        raise httpx.ReadTimeout("slow")
    _client, session = _setup(handler)
    try:
        _request(session, "POST").send(httpx.Headers())
    except httpx.ReadTimeout:
        pass
    else:
        raise AssertionError("a timed-out write was reported as done")
    assert calls == ["POST"]
    calls.clear()
    try:
        _request(session, "GET").send(httpx.Headers())
    except httpx.ReadTimeout:
        pass
    assert calls == ["GET", "GET"]                  # a read is tried again


def test_signed_out_or_offline_nothing_is_forced():
    def handler(req):
        return httpx.Response(200, json=[])
    client, session = _setup(handler, life=60, signed_in=False)
    _request(session).send(httpx.Headers())
    assert client.auth.refreshed == 0
    client, session = _setup(handler, life=60)
    client.auth.fail = True                         # no network for renewal
    assert _request(session).send(httpx.Headers()).status_code == 200
    assert ds.keep_fresh() is True                  # still valid for now
