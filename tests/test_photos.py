"""Stock photos: shrunk before they go up, kept on the PC, fetched together."""
from __future__ import annotations

import io
import tempfile
import threading
from pathlib import Path

from taf_order_app import db, photos


def _photo(w=3000, h=2000, mode="RGB", fmt="JPEG") -> bytes:
    from PIL import Image
    import random
    img = Image.new(mode, (w, h))
    # Noise, so it does not compress to nothing the way a flat colour would.
    rnd = random.Random(1)
    px = img.load()
    for x in range(0, w, 7):
        for y in range(0, h, 7):
            px[x, y] = tuple(rnd.randrange(256) for _ in mode)
    out = io.BytesIO()
    img.save(out, fmt, quality=95)
    return out.getvalue()


def _size(data):
    from PIL import Image
    return Image.open(io.BytesIO(data)).size


def test_a_phone_photo_is_shrunk_before_it_goes_up():
    big = _photo()
    small, mime, ext = photos.shrink(big)
    assert (mime, ext) == ("image/jpeg", ".jpg")
    assert len(small) < len(big)
    assert max(_size(small)) == photos.UPLOAD_MAX
    assert _size(small) == (1200, 800)          # never stretched


def test_a_see_through_png_goes_up_on_white():
    from PIL import Image
    small, mime, ext = photos.shrink(_photo(1600, 1600, "RGBA", "PNG"))
    assert ext == ".jpg"
    assert Image.open(io.BytesIO(small)).mode == "RGB"


def test_what_is_not_a_picture_goes_up_as_it_is():
    assert photos.shrink(b"not a picture") == (b"not a picture", "", "")


def test_a_small_photo_already_small_enough_is_left_alone():
    tiny = _photo(40, 30)
    data, _, _ = photos.shrink(tiny)
    assert _size(data) == (40, 30)


def test_a_new_upload_has_an_address_of_its_own():
    url = "https://x.supabase.co/storage/v1/object/public/stock-images/a.jpg"
    assert photos.versioned(url, 100) == url + "?v=100"
    assert photos.versioned(url + "?v=100", 200.7) == url + "?v=200"
    assert photos.cache_file(url + "?v=1", Path("/c")) != \
        photos.cache_file(url + "?v=2", Path("/c"))


def test_each_photo_is_fetched_once_then_comes_off_the_disk():
    fetched = []

    def fetch(url):
        fetched.append(url)
        return _photo()

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        first = photos.thumbnail("https://x/a.jpg?v=1", folder, fetch)
        assert max(first.size) == photos.THUMB_MAX
        assert photos.cache_file("https://x/a.jpg?v=1", folder).exists()
        again = photos.thumbnail("https://x/a.jpg?v=1", folder, fetch)
        assert again.size == first.size
        assert fetched == ["https://x/a.jpg?v=1"]


def test_a_photo_that_will_not_come_is_none_and_nothing_is_kept():
    def fetch(url):
        raise OSError("offline")

    with tempfile.TemporaryDirectory() as tmp:
        assert photos.thumbnail("https://x/b.jpg", Path(tmp), fetch) is None
        assert list(Path(tmp).iterdir()) == []


def test_a_spoiled_copy_on_the_disk_is_fetched_again():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        photos.cache_file("https://x/c.jpg", folder).write_bytes(b"half a file")
        img = photos.thumbnail("https://x/c.jpg", folder, lambda u: _photo(600, 400))
        assert img is not None and img.size == (480, 320)


def test_they_are_fetched_several_at_a_time_and_each_is_told():
    # Every fetch waits until three are under way at once: one at a time
    # would never get past the first.
    gate = threading.Barrier(3, timeout=5)
    got = {}

    def fetch(url):
        gate.wait()
        return _photo(100, 100)

    urls = ["https://x/1.jpg", "https://x/2.jpg", "https://x/3.jpg", "", "https://x/1.jpg"]
    with tempfile.TemporaryDirectory() as tmp:
        worker = photos.fetch_all(urls, lambda u, img: got.__setitem__(u, img),
                                  Path(tmp), workers=3, fetch=fetch)
        worker.join(10)
    assert sorted(got) == ["https://x/1.jpg", "https://x/2.jpg", "https://x/3.jpg"]
    assert all(img is not None for img in got.values())


class _Store:
    def __init__(self):
        self.removed, self.uploaded = [], []

    def remove(self, names):
        self.removed.extend(names)

    def upload(self, name, data, file_options=None):
        self.uploaded.append((name, data, file_options))


class _Client:
    def __init__(self):
        self.store = _Store()
        self.storage = self

    def from_(self, bucket):
        assert bucket == "stock-images"
        return self.store


def test_an_uploaded_stock_photo_is_shrunk_cached_and_versioned():
    client = _Client()
    original = db.get_client
    db.get_client = lambda: client
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "IMG_0001.PNG"
            path.write_bytes(_photo(2400, 1800, "RGB", "PNG"))
            url = db.upload_stock_image("item-1", str(path))
    finally:
        db.get_client = original
    (name, data, opts), = client.store.uploaded
    assert name == "item-1.jpg"
    assert max(_size(data)) == 1200
    assert opts["content-type"] == "image/jpeg"
    assert opts["cache-control"] == "31536000"
    assert "item-1.png" in client.store.removed     # the old one, as a PNG
    assert "/stock-images/item-1.jpg?v=" in url


def test_a_photo_from_before_is_shrunk_and_put_back_once():
    client = _Client()
    saved = []
    original, original_update = db.get_client, db.update_stock_item
    db.get_client = lambda: client
    db.update_stock_item = lambda item_id, data: saved.append((item_id, data))
    old = "https://x.supabase.co/storage/v1/object/public/stock-images/s9.png"
    try:
        new = db.shrink_stock_photo({"id": "s9", "image_url": old},
                                    fetch=lambda u: _photo(3000, 2000, "RGB", "PNG"))
        # Done already, somewhere else, or none: left alone.
        assert db.shrink_stock_photo({"id": "s9", "image_url": new},
                                     fetch=lambda u: 1 / 0) == ""
        assert db.shrink_stock_photo({"id": "s9", "image_url": "https://elsewhere/p.png"},
                                     fetch=lambda u: 1 / 0) == ""
        assert db.shrink_stock_photo({"id": "s9"}, fetch=lambda u: 1 / 0) == ""
    finally:
        db.get_client, db.update_stock_item = original, original_update
    assert "/stock-images/s9.jpg?v=" in new
    (name, data, _opts), = client.store.uploaded
    assert name == "s9.jpg" and max(_size(data)) == 1200
    assert saved == [("s9", {"image_url": new})]
