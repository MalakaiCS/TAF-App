
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class HeaderData:
    customer_name: str
    order_number: str
    date_ordered: str
    date_due: str = ""
    attention: str = ""
    job: str = ""
    location: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "Customer Name": self.customer_name,
            "Order Number": self.order_number,
            "Date Ordered": self.date_ordered,
            "Date Due": self.date_due,
            "Attention": self.attention,
            "Job": self.job,
            "Location": self.location,
            "Notes": self.notes,
        }

@dataclass
class LineItem:
    quantity: int
    short: int
    long: int
    channel: int
    filter_type: str
    media_type: str
    pleat_insert: bool = False
    header_only: bool = False
    use_stock_v_form: bool = False
    use_stock_flyscreen: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "Quantity": self.quantity,
            "Short": self.short,
            "Long": self.long,
            "Channel": self.channel,
            "Filter Type": self.filter_type,
            "Media Type": self.media_type,
            "Pleat Insert": self.pleat_insert,
            "Header": self.header_only,
            "Use Stock V-form": self.use_stock_v_form,
            "Use Stock Flyscreen": self.use_stock_flyscreen,
            "Notes": self.notes,
        }
