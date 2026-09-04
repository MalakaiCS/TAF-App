
from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
from typing import List, Dict, Any, Optional

from .validation import validate_header, validate_items
from template_filler import generate_order_workbook

class OrderService:
    """
    Business layer: validates, persists (optional), and generates the Excel/PDF outputs.
    """

    def __init__(self, base_dir: Optional[Path] = None):
        # Never derive the orders location from the current working directory:
        # when the app is relaunched by the updater (or any service), cwd can
        # be C:\Windows\System32 — mkdir there is Access Denied and crashed
        # startup. Anchor to the app data dir instead (same as the GUI's
        # APP_DIR): %APPDATA%\TAF Order Entry when frozen, repo dir otherwise.
        import os, sys
        if base_dir is not None:
            self.base_dir = Path(base_dir)
        elif getattr(sys, "frozen", False):
            self.base_dir = Path(os.environ.get("APPDATA", Path.home())) / "TAF Order Entry"
        else:
            self.base_dir = Path(__file__).resolve().parents[1]
        self.orders_dir = self.base_dir / "orders"
        try:
            self.orders_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Last-ditch fallback — never let folder creation kill startup.
            import tempfile
            self.orders_dir = Path(tempfile.gettempdir()) / "TAF Order Entry" / "orders"
            self.orders_dir.mkdir(parents=True, exist_ok=True)

    def save_order_json(self, header: Dict[str, Any], items: List[Dict[str, Any]]) -> Path:
        safe_customer = "".join(c for c in (header.get("Customer Name","") or "") if c.isalnum() or c in (" ","_","-")).strip().replace(" ", "_")
        safe_order = "".join(c for c in (header.get("Order Number","") or "") if c.isalnum() or c in ("_","-")).strip()
        name = f"{safe_customer}_{safe_order}".strip("_") or "order"
        path = self.orders_dir / f"{name}.json"
        # Determine order_type from items present
        has_filter = any(i.get("item_kind", "filter") != "bag" for i in items)
        has_bag    = any(i.get("item_kind") == "bag"            for i in items)
        if has_filter and has_bag:
            order_type = "mixed"
        elif has_bag:
            order_type = "bags"
        else:
            order_type = "filter"
        payload = {"order_type": order_type, "header": header, "items": items}
        path.write_text(json.dumps(payload, indent=2))
        return path

    def create_order(self, header: Dict[str, Any], items: List[Dict[str, Any]],
                     persist_json: bool = True,
                     extra_media_types: List[str] = None,
                     auto_open: bool = True,
                     page_start: int = 1,
                     grand_total: int = None,
                     extra_filter_types: List[str] = None) -> Dict[str, Any]:
        # Validate
        validate_header(header)
        validate_items(items, extra_media_types=extra_media_types,
                       extra_filter_types=extra_filter_types)

        # Persist
        json_path = None
        if persist_json:
            json_path = self.save_order_json(header, items)

        # Generate output via existing engine
        # Ensure we run from the folder that contains Templates.xlsx (same folder as template_filler.py)
        import os
        from contextlib import contextmanager

        @contextmanager
        def _pushd(path: Path):
            prev = Path.cwd()
            os.chdir(path)
            try:
                yield
            finally:
                os.chdir(prev)

        import sys
        if getattr(sys, "frozen", False):
            template_dir = Path(sys._MEIPASS)
        else:
            template_dir = Path(__file__).resolve().parents[1]  # contains template_filler.py + Templates.xlsx
        with _pushd(template_dir):
            output_path = generate_order_workbook(header, items, auto_open=auto_open,
                                                  page_start=page_start,
                                                  grand_total=grand_total)

        return {"output_path": output_path, "json_path": str(json_path) if json_path else None}
