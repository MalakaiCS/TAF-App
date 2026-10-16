"""Keeping the database connection alive for a whole working day.

The sign-in gives a token that lasts an hour. The database library renews it
on a single timer; if the renewal fails - the PC asleep, the wifi dropped,
the office connection blinking - it retries for a minute or two, then stops
for good. An hour later every request is refused with "JWT expired", and the
only cure was to sign out and in again. Idle connections go stale as well,
and the next request on one fails with "Server disconnected".

This sits where every database request is sent from (postgrest's
RequestConfig.send - tables, rpc, inserts, all of it), and:

  * renews the token first when it has less than five minutes left;
  * on "JWT expired" / 401 anyway, renews and sends the request once more;
  * on a stale or dropped connection, sends once more on a fresh one - a
    read always, a write only when it can't have reached the server, so
    nothing is saved twice;

and a watchdog thread renews the token ahead of time, every minute it is
due, until it manages - so a laptop that slept through its renewal is fixed
the moment it is back on the network.
"""
from __future__ import annotations

import threading
import time

REFRESH_MARGIN = 300          # seconds of token life left that trigger renewal
WATCH_EVERY = 60              # seconds between the watchdog's looks

_lock = threading.Lock()
_watchdog = None
_get_client = None            # set by install(): db.get_client
_signed_in = None             # set by install(): () -> bool
_last_failed = 0.0


def _stored_session(client):
    """The session as stored, without the library's own get_session(),
    which tries a renewal of its own and can sign out on the way."""
    auth = client.auth
    try:
        if getattr(auth, "_persist_session", False):
            raw = auth._storage.get_item(auth._storage_key)
            return auth._get_valid_session(raw)
        return getattr(auth, "_in_memory_session", None)
    except Exception:
        return None


def keep_fresh(force: bool = False) -> bool:
    """Renew the sign-in token if it is near its end (or `force`). True when
    there is a usable session afterwards."""
    global _last_failed
    if _get_client is None or not (_signed_in and _signed_in()):
        return False
    try:
        client = _get_client()
    except Exception:
        return False
    with _lock:
        session = _stored_session(client)
        if session is None or not getattr(session, "expires_at", None):
            return False
        left = session.expires_at - time.time()
        if not force and left > REFRESH_MARGIN:
            return True
        # Not more than once every few seconds when the network is down -
        # each request would otherwise wait on a renewal that cannot work.
        if not force and time.monotonic() - _last_failed < 5:
            return left > 0
        try:
            client.auth.refresh_session(session.refresh_token)
            return True
        except Exception:
            _last_failed = time.monotonic()
            return left > 0


def _bearer():
    try:
        return _get_client().options.headers.get("Authorization")
    except Exception:
        return None


def _is_expired_token(resp) -> bool:
    if resp.status_code == 401:
        return True
    if resp.status_code in (400, 403):
        try:
            body = resp.text or ""
        except Exception:
            body = ""
        return "JWT expired" in body or "PGRST301" in body \
            or "PGRST303" in body
    return False


def install(get_client, signed_in) -> None:
    """Wrap postgrest's request sending once, and start the watchdog."""
    global _get_client, _signed_in
    _get_client, _signed_in = get_client, signed_in
    try:
        import httpx
        from postgrest import base_request_builder as brb
    except Exception:
        return
    if getattr(brb.RequestConfig, "_taf_kept_fresh", False):
        return
    original = brb.RequestConfig.send

    # Connection failures where the request never reached the database:
    # safe to send again, writes included.
    never_arrived = tuple(getattr(httpx, n) for n in (
        "ConnectError", "ConnectTimeout", "PoolTimeout",
        "RemoteProtocolError") if hasattr(httpx, n))
    # Failures after it may have arrived: only a read is sent again.
    maybe_arrived = tuple(getattr(httpx, n) for n in (
        "ReadTimeout", "ReadError", "WriteError", "WriteTimeout")
        if hasattr(httpx, n))

    def send(self, additional_headers):
        if not isinstance(self.session, httpx.Client):
            return original(self, additional_headers)
        extra = dict(additional_headers.items()) if additional_headers else {}

        def attempt():
            bearer = _bearer()
            if bearer and _signed_in and _signed_in():
                self.headers["Authorization"] = bearer
            return original(self, httpx.Headers(extra))

        keep_fresh()
        reading = self.http_method in ("GET", "HEAD")
        try:
            resp = attempt()
        except never_arrived:
            time.sleep(0.3)
            resp = attempt()
        except maybe_arrived:
            if not reading:
                raise
            time.sleep(0.3)
            resp = attempt()
        if _is_expired_token(resp) and keep_fresh(force=True):
            resp = attempt()
        return resp

    brb.RequestConfig.send = send
    brb.RequestConfig._taf_kept_fresh = True
    start_watchdog()


def start_watchdog() -> None:
    global _watchdog
    if _watchdog is not None and _watchdog.is_alive():
        return

    def _watch():
        while True:
            time.sleep(WATCH_EVERY)
            try:
                keep_fresh()
            except Exception:
                pass
    _watchdog = threading.Thread(target=_watch, daemon=True,
                                 name="db-session-watchdog")
    _watchdog.start()
