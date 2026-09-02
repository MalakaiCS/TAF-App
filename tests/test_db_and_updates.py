"""
The parts that talk to the outside world, with the outside world faked.

Three shipped bugs live here. All three looked like success at the time:
a purchase order matched to the wrong branch of the right company, a price
list read back as its first thousand rows, and an update check that reported
"you're up to date" when it had never reached GitHub.
"""
import json
import urllib.error

from taf_order_app import db
from taf_order_app import updater


# ── Matching a purchase order to a branch ───────────────────────────────────
# A Bells Creek order was written up as CAS - Tweed, because creating the
# Tweed profile had saved "Complete Air Supply Pty Ltd" as wording belonging
# to Tweed — and every branch of the company prints that.

LEGAL = "Complete Air Supply Pty Ltd"
BELLS_ADDR = ("Complete Air Supply - Bells Creek (MOR), 19-27 Fred Chaplin "
              "Circuit, Bells Creek QLD 4551")
TWEED_ADDR = ("Complete Air Supply - Tweed (TWD), 5 Kite Crescent, "
              "South Murwillumbah NSW 2484")

TWEED = {"id": "tweed", "short_name": "CAS - Tweed", "name": LEGAL,
         "legal_name": LEGAL, "delivery_address1": "5 Kite Crescent",
         "delivery_city": "South Murwillumbah", "delivery_postcode": "2484",
         "po_aliases": [LEGAL, TWEED_ADDR]}       # LEGAL is the legacy bad one
BELLS = {"id": "bells", "short_name": "CAS - Bells Creek", "name": LEGAL,
         "legal_name": LEGAL, "delivery_address1": "19-27 Fred Chaplin Circuit",
         "delivery_city": "Bells Creek", "delivery_postcode": "4551",
         "po_aliases": [LEGAL, BELLS_ADDR]}
ACME = {"id": "acme", "short_name": "Acme Air", "name": "Acme Air",
        "legal_name": "Acme Air Pty Ltd", "delivery_address1": "7 Trade Link Road",
        "delivery_city": "Hillcrest", "delivery_postcode": "4118",
        "po_aliases": []}


def test_a_company_name_alone_never_picks_a_branch():
    # Only Tweed on file, carrying the legacy company-name alias.
    assert db.match_customer(LEGAL, BELLS_ADDR, [TWEED]) is None
    assert db.match_customer(LEGAL, "", [TWEED, BELLS]) is None


def test_the_address_decides_which_branch():
    assert db.match_customer(LEGAL, BELLS_ADDR, [TWEED, BELLS, ACME])["id"] == "bells"
    assert db.match_customer(LEGAL, TWEED_ADDR, [TWEED, BELLS, ACME])["id"] == "tweed"


def test_a_short_name_identifies_a_branch_on_its_own():
    got = db.match_customer("CAS - Bells Creek", "", [TWEED, BELLS, ACME])
    assert got["id"] == "bells"


def test_an_ordinary_customer_still_matches():
    assert db.match_customer("Acme Air", "", [TWEED, BELLS, ACME])["id"] == "acme"
    got = db.match_customer("Acme Air Pty Ltd", "7 Trade Link Road, Hillcrest",
                            [TWEED, BELLS, ACME])
    assert got["id"] == "acme"


def test_a_blank_legal_name_does_not_reopen_the_hole():
    blank = dict(BELLS, legal_name="", id="blank")
    assert db.match_customer(LEGAL, "somewhere else", [TWEED, blank]) is None


def test_is_company_name():
    assert db.is_company_name(LEGAL, [TWEED, BELLS])
    assert not db.is_company_name("CAS - Bells Creek", [TWEED, BELLS])
    assert not db.is_company_name("", [TWEED, BELLS])


# ── Reading a long price list ───────────────────────────────────────────────
# PostgREST returns at most 1000 rows. Without paging, a 12,480-row price
# list came back as its first thousand part numbers and every lookup past
# those missed — which looked exactly like "the prices didn't import".

class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._lo, self._hi = 0, 999

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def or_(self, *a, **k):
        return self

    def range(self, lo, hi):
        self._lo, self._hi = lo, hi
        return self

    def execute(self):
        # The cap is the point of this fake.
        window = self._rows[self._lo:self._hi + 1][:1000]
        return type("R", (), {"data": window, "count": len(self._rows)})()

    def limit(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return _FakeQuery(self._rows)


def _with_fake_client(rows):
    client = _FakeClient(rows)
    original = db.get_client
    db.get_client = lambda: client
    return original


def test_a_long_price_list_is_read_in_full(monkeypatch=None):
    rows = [{"part_number": f"FPFG425-{n:04d}", "unit_price": n, "name": ""}
            for n in range(1, 12481)]
    original = _with_fake_client(rows)
    try:
        got = db.get_price_rows()
        assert len(got) == 12480, f"only read {len(got)} of 12480"
        prices = db.get_price_list()
        assert len(prices) == 12480
        assert "FPFG425-12480" in prices        # the last one is reachable
        assert db.count_prices() == 12480
    finally:
        db.get_client = original


def test_a_price_list_read_honours_a_limit():
    rows = [{"part_number": f"P{n}", "unit_price": n} for n in range(1, 5000)]
    original = _with_fake_client(rows)
    try:
        assert len(db.get_price_rows(limit=2500)) == 2500
    finally:
        db.get_client = original


# ── Checking for an update ──────────────────────────────────────────────────
# "You're up to date" was said whether GitHub had answered or not, leaving
# someone on an old build certain they were on the newest one.

class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(result):
    def _open(req, timeout=None):
        if isinstance(result, Exception):
            raise result
        return _FakeResponse(result)
    return _open


def _patch_urlopen(opener):
    original = updater.urllib.request.urlopen
    updater.urllib.request.urlopen = opener
    return original


RELEASE = {"tag_name": "v9.9.9", "body": "notes",
           "assets": [{"name": "TAFOrderEntry_Setup.exe",
                       "browser_download_url": "https://example/setup.exe"}]}


def test_a_newer_release_is_found():
    original = _patch_urlopen(_fake_urlopen(RELEASE))
    try:
        info = updater.latest_release()
        assert info["version"] == "9.9.9" and info["is_newer"]
        assert info["download_url"].endswith("setup.exe")
    finally:
        updater.urllib.request.urlopen = original


def test_being_current_is_reported_as_such():
    payload = dict(RELEASE, tag_name=f"v{updater.APP_VERSION}")
    original = _patch_urlopen(_fake_urlopen(payload))
    try:
        info = updater.latest_release()
        assert not info["is_newer"]
        assert updater.check_for_update() is None
    finally:
        updater.urllib.request.urlopen = original


def test_a_failed_check_raises_instead_of_looking_current():
    failure = urllib.error.URLError("connection refused")
    original = _patch_urlopen(_fake_urlopen(failure))
    try:
        raised = False
        try:
            updater.latest_release()
        except updater.UpdateCheckError as exc:
            raised = True
            assert "couldn't reach GitHub" in str(exc)
        assert raised, "a failed check must not pass for an answer"
        # The silent startup check may still swallow it — nobody is watching.
        assert updater.check_for_update() is None
    finally:
        updater.urllib.request.urlopen = original


def test_rate_limiting_says_so():
    err = urllib.error.HTTPError(
        "u", 403, "rate limited",
        {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}, None)
    original = _patch_urlopen(_fake_urlopen(err))
    try:
        try:
            updater.latest_release()
            assert False, "expected UpdateCheckError"
        except updater.UpdateCheckError as exc:
            assert "rate-limiting" in str(exc)
    finally:
        updater.urllib.request.urlopen = original


def test_version_comparison():
    assert updater.is_newer("2.13.0", "2.12.1")
    assert updater.is_newer("2.10.0", "2.9.9")
    assert not updater.is_newer("2.13.0", "2.13.0")
    assert not updater.is_newer("2.12.1", "2.13.0")
    assert updater.is_newer("v2.13.0", "2.12.0")
