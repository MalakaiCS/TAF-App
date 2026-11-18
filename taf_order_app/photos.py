"""Stock photos that load quickly.

They were slow because they went up as they came off a phone - several
megabytes and four thousand pixels across, for a picture shown two hundred
wide - and every PC fetched every one again, one after another, each time
the Stock page was opened.

Now:
  * a photo is shrunk before it is uploaded (`shrink`), to a size that
    still looks sharp on a big screen and is a small fraction of the bytes;
  * each upload has an address of its own (`?v=` the time), so a phone's
    browser and this PC can keep it without ever showing an old one;
  * each PC keeps a small copy (`thumbnail`), so after the first time a
    photo comes off the disk, not the internet;
  * and they are fetched several at a time (`fetch_all`).
"""
from __future__ import annotations

import hashlib
import io
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

UPLOAD_MAX = 1200          # pixels on the longest side
THUMB_MAX = 480            # what a card ever shows, with room for a big screen
FETCHERS = 6               # photos fetched at once


def _pil():
    from PIL import Image, ImageOps
    return Image, ImageOps


def _upright_rgb(img):
    """Turned the way the camera was held, and on white if see-through."""
    Image, ImageOps = _pil()
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        back = Image.new("RGB", img.size, (255, 255, 255))
        back.paste(img, mask=img.getchannel("A"))
        return back
    return img.convert("RGB")


def shrink(data: bytes, longest: int = UPLOAD_MAX) -> Tuple[bytes, str, str]:
    """A photo made fit to upload: at most `longest` pixels across, a
    progressive JPEG. (bytes, content type, extension). Anything that will
    not open as a picture is handed back untouched."""
    try:
        Image, _ = _pil()
        img = Image.open(io.BytesIO(data))
        img.draft("RGB", (longest, longest))      # a JPEG decodes small, fast
        img = _upright_rgb(img)
        img.thumbnail((longest, longest), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=85, optimize=True, progressive=True)
        small = out.getvalue()
        if len(small) < len(data):
            return small, "image/jpeg", ".jpg"
    except Exception:
        pass
    return data, "", ""


def cache_dir() -> Path:
    from .paths import user_data_dir
    path = user_data_dir(create=True) / "photo-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_file(url: str, folder: Optional[Path] = None) -> Path:
    """Where this PC keeps its small copy of a photo. The address names the
    file - and a new upload has a new address - so a changed photo is
    never mistaken for the old one."""
    key = hashlib.sha1(url.strip().encode("utf-8")).hexdigest()
    return (folder or cache_dir()) / f"{key}.jpg"


def thumbnail(url: str, folder: Optional[Path] = None,
              fetch: Optional[Callable[[str], bytes]] = None):
    """The photo at `url`, small enough for a card: from this PC's copy if
    there is one, otherwise fetched once and kept. A PIL image, or None."""
    Image, _ = _pil()
    path = cache_file(url, folder)
    if path.exists():
        try:
            img = Image.open(path)
            img.load()
            return img
        except Exception:
            path.unlink(missing_ok=True)
    try:
        if fetch is not None:
            data = fetch(url)
        elif url.startswith("http"):
            with urllib.request.urlopen(url, timeout=20) as resp:
                data = resp.read()
        else:
            data = Path(url).read_bytes()
        img = Image.open(io.BytesIO(data))
        img.draft("RGB", (THUMB_MAX, THUMB_MAX))
        img = _upright_rgb(img)
        img.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
    except Exception:
        return None
    try:
        tmp = path.with_suffix(".part")
        img.save(tmp, "JPEG", quality=88)
        tmp.replace(path)
    except Exception:
        pass
    return img


def fetch_all(urls: Iterable[str], arrived: Callable[[str, object], None],
              folder: Optional[Path] = None, workers: int = FETCHERS,
              fetch: Optional[Callable[[str], bytes]] = None) -> threading.Thread:
    """Get every photo, several at a time, off the calling thread; `arrived`
    is called for each (from a worker thread) as it comes in."""
    todo = [u for u in dict.fromkeys(urls) if u]

    def _run():
        # Each as it comes in - one slow photo holds up nobody else's.
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            jobs = {pool.submit(thumbnail, u, folder, fetch): u for u in todo}
            for job in as_completed(jobs):
                try:
                    img = job.result()
                except Exception:
                    img = None
                arrived(jobs[job], img)
    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    return worker


def versioned(url: str, stamp: int) -> str:
    """The address of an upload, made its own: the same file uploaded again
    gets a new address, so nothing that kept the old one shows it."""
    base = url.split("?", 1)[0]
    return f"{base}?v={int(stamp)}"
