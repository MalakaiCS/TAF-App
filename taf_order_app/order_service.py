
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
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.orders_dir = self.base_dir / "orders"
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
                     grand_total: int = None) -> Dict[str, Any]:
        # Validate
        validate_header(header)
        validate_items(items, extra_media_types=extra_media_types)

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
