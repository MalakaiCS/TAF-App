"""What open orders have spoken for, supplier prices, and what to order
before it runs out."""
from __future__ import annotations

import datetime as _dt

from taf_order_app import stock_insight as si

TODAY = _dt.date(2026, 10, 16)
STOCK = [
    {"id": "m1", "name": "G4 media roll", "sku": "G4", "product_type": "Media Roll",
     "unit": "m2", "stock_on_hand": 40, "minimum_on_hand": 10},
    {"id": "p1", "name": "Panel", "sku": "FPFG425-040", "stock_on_hand": 5,
     "minimum_on_hand": 2},
]


def test_open_orders_speak_for_stock_and_made_lines_do_not():
    orders = [
        {"order_number": "A", "header": {"status": "Pending"}, "items": [
            {"Quantity": 3, "Part Number": "FPFG425-040"},
            {"Quantity": 2, "Media Type": "G4", "Short": 500, "Long": 500},
            {"Quantity": 9, "Part Number": "FPFG425-040", "made": True}]},
        {"order_number": "B", "header": {"status": "In Production"}, "items": [
            {"Quantity": 1, "Part Number": "FPFG425-040"}]},
        {"order_number": "C", "header": {"status": "Complete"}, "items": [
            {"Quantity": 50, "Part Number": "FPFG425-040"}]},
        {"order_number": "D", "archived": True, "items": [
            {"Quantity": 50, "Part Number": "FPFG425-040"}]},
    ]
    got = si.reserved_by_item(orders, STOCK)
    assert got["p1"] == {"reserved": 4.0, "orders": 2}
    assert got["m1"] == {"reserved": 0.6, "orders": 1}       # 2 x 0.3 m2
    assert si.free(STOCK[1], got) == 1.0
    assert si.free({"id": "x", "stock_on_hand": 7}, got) == 7.0


def test_what_has_been_paid_is_in_order_with_its_change():
    rows = [
        {"bought_at": "2026-03-01T00:00:00Z", "supplier": "FDG", "item_code": "CC45",
         "unit_price": 18.5, "quantity": 20, "po_number": "PO-1"},
        {"bought_at": "2026-01-01T00:00:00Z", "supplier": "FDG", "item_code": "cc45",
         "unit_price": 17.0, "po_number": "PO-0"},
        {"bought_at": "2026-02-01T00:00:00Z", "supplier": "AD", "stock_item_id": "st",
         "item_code": "AD-45", "unit_price": 19.0},
        {"bought_at": "2026-04-01T00:00:00Z", "supplier": "FDG", "item_code": "OTHER",
         "unit_price": 99},
    ]
    got = si.price_history(rows, "st", ["CC45"])
    assert [(h["day"].isoformat(), h["supplier"], h["price"], h["change"])
            for h in got] == [("2026-01-01", "FDG", 17.0, None),
                              ("2026-02-01", "AD", 19.0, None),
                              ("2026-03-01", "FDG", 18.5, 8.8)]


def test_stock_that_will_run_out_before_more_can_arrive():
    stock = [
        {"id": "a", "name": "Channel 45", "stock_on_hand": 30, "minimum_on_hand": 10},
        {"id": "b", "name": "Tape", "stock_on_hand": 100, "minimum_on_hand": 10},
        {"id": "c", "name": "Rivets", "stock_on_hand": 5, "minimum_on_hand": 10},
        {"id": "d", "name": "Idle", "stock_on_hand": 20, "minimum_on_hand": 10},
    ]
    tx = ([{"stock_item_id": "a", "transaction_type": "use", "quantity_change": -6,
            "created_at": f"2026-10-{d:02d}T00:00:00Z"} for d in range(1, 11)]
          + [{"stock_item_id": "b", "transaction_type": "use", "quantity_change": -6,
              "created_at": "2026-10-10T00:00:00Z"},
             {"stock_item_id": "a", "transaction_type": "receive", "quantity_change": 99,
              "created_at": "2026-10-10T00:00:00Z"}])
    links = [{"stock_item_id": "a", "supplier_id": "s1", "preferred": True}]
    leads = [{"supplier_id": "s1", "supplier": "FD Greenwood", "median_days": 21}]
    got = si.order_soon(stock, tx, links, leads, TODAY)
    assert [r["item"]["id"] for r in got] == ["c", "a"]
    a = got[1]
    assert (a["per_day"], a["days_left"], a["lead_days"], a["supplier"]) == \
        (1.0, 20.0, 21, "FD Greenwood")
    assert a["order"] == 1.0                     # 10 - 30 + 1 x 21
    c = got[0]
    assert c["days_left"] == 0 and c["lead_days"] == 7.0 and c["order"] == 5.0
