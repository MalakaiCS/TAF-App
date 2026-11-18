"""Certificates for the app's own HTTPS requests.

urllib checks a website's certificate against a list of trusted roots that
it finds where OpenSSL was told to look when Python was built. On Windows it
also reads the system's list. A packaged Mac app has neither: it looks in a
folder on the build machine that does not exist on anybody else's Mac, finds
nothing, and every https request fails with CERTIFICATE_VERIFY_FAILED. On a
Mac that was the update check, the update download and the profile photo.

certifi's bundle travels with the app (the database client already needs
it), so it is added to whatever the system provides - never instead of it,
so an office's own certificates on Windows keep working.

Imported first, by the app's entry point and the updater.
"""
from __future__ import annotations

import ssl


def context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass                       # the system's list alone, as before
    return ctx


def install() -> None:
    if getattr(ssl, "_taf_certifi", False):
        return
    ssl._create_default_https_context = context
    ssl._taf_certifi = True


install()
