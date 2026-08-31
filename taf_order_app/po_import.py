"""
Purchase-order import — turn an uploaded PDF, photo, scan or email into
order data the app can generate worksheets from.

The reading is done by the `extract-orders` Supabase Edge Function (see
supabase/functions/extract-orders/index.ts), which holds the Anthropic API
key server-side. This module only prepares the files, calls that function
with the signed-in user's token, and maps the result onto the app's own
header / line-item dictionaries.

Nothing here writes an order — everything goes through the review dialog
first, because a misread dimension costs a scrapped filter.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from . import db as _db

# Formats we can hand to the extractor. Anything else is rejected up front
# with a clear message rather than failing halfway through the call.
IMAGE_TYPES = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
}
TEXT_SUFFIXES = {".txt", ".eml", ".msg", ".csv"}
SUPPORTED_SUFFIXES = set(IMAGE_TYPES) | TEXT_SUFFIXES | {".pdf"}

# The API caps a request at 32 MB; base64 inflates by ~4/3, so keep the raw
# payload comfortably under that.
MAX_TOTAL_BYTES = 20 * 1024 * 1024


class POImportError(RuntimeError):
    """Raised with a message intended to be shown to the user as-is."""


def is_configured() -> bool:
    """True when the app has a signed-in session to call the function with."""
    return bool(_db.is_ready() and _db.current_user())


def _function_url() -> str:
    base = _db.SUPABASE_URL.rstrip("/")
    return f"{base}/functions/v1/extract-orders"


def _access_token() -> str:
    """The signed-in user's access token (the Edge Function verifies it)."""
    try:
        session = _db.get_client().auth.get_session()
        token = getattr(session, "access_token", "") if session else ""
    except Exception:
        token = ""
    if not token:
        raise POImportError("You need to be signed in to import purchase orders.")
    return token


def prepare_files(paths: List[str]) -> List[Dict[str, Any]]:
    """Read the chosen files into the payload the Edge Function expects."""
    payload: List[Dict[str, Any]] = []
    total = 0
    for p in paths:
        path = Path(p)
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise POImportError(
                f"{path.name} is a {suffix or 'unknown'} file.\n\n"
                "Supported: PDF, PNG, JPG, GIF, WEBP, and plain-text/email files.")
        try:
            raw = path.read_bytes()
        except Exception as exc:
            raise POImportError(f"Could not read {path.name}:\n{exc}")

        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise POImportError(
                "Those files add up to more than 20 MB.\n\n"
                "Import them in smaller batches, or photograph pages at a "
                "lower resolution.")

        if suffix in TEXT_SUFFIXES:
            try:
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                text = ""
            if not text.strip():
                raise POImportError(f"{path.name} appears to be empty.")
            payload.append({"name": path.name, "text": text})
            continue

        media_type = (IMAGE_TYPES.get(suffix)
                      or mimetypes.guess_type(path.name)[0]
                      or "application/pdf")
        payload.append({
            "name":       path.name,
            "media_type": media_type,
            "data":       base64.standard_b64encode(raw).decode("ascii"),
        })
    if not payload:
        raise POImportError("No files selected.")
    return payload


def extract_orders(paths: List[str], timeout: int = 300) -> List[Dict[str, Any]]:
    """Send the documents for reading and return normalised app orders.

    Blocks for as long as the extraction takes, so call it on a background
    thread. Raises POImportError with a user-facing message on any failure.
    """
    files = prepare_files(paths)
    token = _access_token()

    body = json.dumps({"files": files}).encode("utf-8")
    req = urllib.request.Request(
        _function_url(),
        data=body,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = (json.loads(exc.read().decode("utf-8")) or {}).get("error", "")
        except Exception:
            pass
        if exc.code == 404:
            raise POImportError(
                "The purchase-order reader isn't set up on this Supabase "
                "project yet.\n\n"
                "An admin needs to deploy the 'extract-orders' Edge Function "
                "and set the ANTHROPIC_API_KEY secret — see the README.")
        if exc.code in (401, 403):
            raise POImportError(
                "The purchase-order reader rejected this sign-in.\n\n"
                "Try signing out and back in; if it persists, an admin should "
                "check the Edge Function's settings.")
        raise POImportError(detail or f"The reader returned an error ({exc.code}).")
    except urllib.error.URLError as exc:
        raise POImportError(
            f"Couldn't reach the purchase-order reader:\n{exc.reason}\n\n"
            "Check the internet connection and try again.")
    except Exception as exc:
        raise POImportError(f"Import failed:\n{exc}")

    if isinstance(data, dict) and data.get("error"):
        raise POImportError(str(data["error"]))

    raw_orders = (data or {}).get("orders") or []
    return [_normalise_order(o) for o in raw_orders if isinstance(o, dict)]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _normalise_order(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map one extracted order onto the app's header / item dictionaries."""
    header = {
        "Customer Name": (raw.get("customer_name") or "").strip(),
        "Order Number":  (raw.get("order_number")  or "").strip(),
        "Date Ordered":  (raw.get("date_ordered")  or "").strip(),
        "Date Due":      (raw.get("date_due")      or "").strip(),
        "Attention":     (raw.get("attention")     or "").strip(),
        "Job":           (raw.get("job")           or "").strip(),
        "Location":      (raw.get("location")      or "").strip(),
        "Notes":         (raw.get("notes")         or "").strip(),
    }

    items: List[Dict[str, Any]] = []
    for it in (raw.get("items") or []):
        if not isinstance(it, dict):
            continue
        short   = _int(it.get("short"))
        long_   = _int(it.get("long"))
        # The extractor is told smaller-then-larger, but a swapped pair is
        # cheap to correct here and avoids a pointless review flag.
        if short and long_ and short > long_:
            short, long_ = long_, short
        items.append({
            "item_kind":           "bag" if it.get("item_kind") == "bag" else "filter",
            "Quantity":            max(1, _int(it.get("quantity"), 1)),
            "Short":               short,
            "Long":                long_,
            "Channel":             _int(it.get("channel")),
            "Filter Type":         (it.get("filter_type") or "").strip(),
            "Media Type":          (it.get("media_type")  or "").strip(),
            "Notes":               (it.get("notes")       or "").strip(),
            "Pleat Insert":        False,
            "Header":              False,
            "Use Stock V-form":    False,
            "Use Stock Flyscreen": False,
            # Review-only metadata — stripped before the order is generated.
            "_confidence":         (it.get("confidence") or "medium").lower(),
            "_source_text":        (it.get("source_text") or "").strip(),
        })

    return {
        "header":     header,
        "items":      items,
        "confidence": (raw.get("confidence") or "medium").lower(),
        "warnings":   [str(w) for w in (raw.get("warnings") or [])],
    }


def strip_review_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the underscore-prefixed review metadata before generating."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


# ── Phone inbox ──────────────────────────────────────────────────────────────
# Photos sent from a phone land in the `po-inbox` bucket. The app sweeps for
# finished batches, brings each one down to this PC, reads it, and clears the
# cloud copy. The extracted orders wait locally until someone reviews them, so
# a cancelled review never loses the photos.

def _inbox_dir(app_dir: Path) -> Path:
    d = Path(app_dir) / "phone_inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_new_batches(app_dir: Path, pair_id: str = "") -> List[str]:
    """Download and read any finished phone batches meant for this PC.

    A phone paired by QR code stamps its batches with that PC's pairing id, so
    two office PCs never race for the same photos. Batches with no pairing id
    (a phone using the plain link) are picked up by whoever sweeps first.

    Returns the batch ids newly made ready for review. Safe to call on a timer;
    stays silent when offline or when the bucket doesn't exist yet.
    """
    if not is_configured():
        return []
    try:
        batches = _db.list_po_inbox_batches()
    except Exception:
        return []          # offline, or migrate_po_inbox.sql not run yet

    ready: List[str] = []
    for b in batches:
        batch  = b["batch"]
        photos = b["photos"]
        sent_to = ((b.get("manifest") or {}).get("pair_id") or "").strip()
        if sent_to and pair_id and sent_to != pair_id:
            continue       # addressed to a different PC — leave it alone
        dest   = _inbox_dir(app_dir) / batch
        if (dest / "orders.json").exists():
            continue       # already read and waiting for review
        try:
            dest.mkdir(parents=True, exist_ok=True)
            local: List[str] = []
            for name in photos:
                p = dest / name
                if not p.exists():
                    p.write_bytes(_db.download_po_photo(batch, name))
                local.append(str(p))

            orders = extract_orders(local)

            manifest = b.get("manifest") or {}
            note = (manifest.get("note") or "").strip()
            for o in orders:
                # The sender's note belongs with the order, and who sent it is
                # worth showing on the review screen.
                if note:
                    existing = (o["header"].get("Notes") or "").strip()
                    o["header"]["Notes"] = f"{existing}\n{note}".strip()
                o["source"] = "phone"
                o["sent_by"] = manifest.get("sent_by", "")
            (dest / "orders.json").write_text(
                json.dumps({
                    "batch":    batch,
                    "sent_by":  manifest.get("sent_by", ""),
                    "sent_at":  manifest.get("sent_at", ""),
                    "note":     note,
                    "photos":   photos,
                    "orders":   orders,
                }, indent=2, default=str),
                encoding="utf-8")
            # Only now is the cloud copy redundant — the photos and what was
            # read from them are both on this PC.
            _db.delete_po_batch(batch, photos)
            ready.append(batch)
        except POImportError:
            # Reading failed (no API key, unreadable photos). Leave the cloud
            # copy in place so it retries, and don't wedge the sweep.
            continue
        except Exception:
            continue
    return ready


def pending_batches(app_dir: Path) -> List[Dict[str, Any]]:
    """Batches read and waiting for someone to review them, oldest first."""
    out: List[Dict[str, Any]] = []
    try:
        folders = sorted(_inbox_dir(app_dir).iterdir())
    except Exception:
        return out
    for d in folders:
        f = d / "orders.json"
        if not f.is_file():
            continue
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("orders"):
            payload["dir"] = str(d)
            out.append(payload)
    return out


def clear_batch(app_dir: Path, batch: str) -> None:
    """Discard a batch once it has been generated or dismissed."""
    import shutil
    try:
        shutil.rmtree(_inbox_dir(app_dir) / batch, ignore_errors=True)
    except Exception:
        pass
