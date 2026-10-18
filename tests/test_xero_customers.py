"""Customers and their contacts in Xero: terms both ways, a contact made from
the app, and only the blanks of an existing one filled in."""
from __future__ import annotations

from taf_order_app import xero as xr

CUSTOMER = {
    "id": "c1", "name": "Bells Creek", "legal_name": "Bells Creek Pty Ltd",
    "email": "accounts@bells.example", "phone": "07 5555 1234",
    "contact_person": "Jo Smith", "abn": "12 345 678 901",
    "delivery_address1": "12 Industrial Ave", "delivery_address2": "",
    "delivery_city": "Caloundra", "delivery_state": "QLD",
    "delivery_postcode": "4551", "delivery_country": "Australia",
    "billing_same": True, "payment_terms": "Net 30",
}


def test_payment_terms_from_xero_read_as_the_app_writes_them():
    cases = [({"Type": "DAYSAFTERBILLDATE", "Day": 30}, "Net 30"),
             ({"Type": "DAYSAFTERBILLDATE", "Day": 0}, "COD"),
             ({"Type": "DAYSAFTERBILLMONTH", "Day": 0}, "EOM"),
             ({"Type": "DAYSAFTERBILLMONTH", "Day": 14}, "14 days after the end of the month"),
             ({"Type": "OFFOLLOWINGMONTH", "Day": 20}, "20th of the following month"),
             ({"Type": "OFFOLLOWINGMONTH", "Day": 1}, "1st of the following month"),
             ({"Type": "OFCURRENTMONTH", "Day": 22}, "22nd of the month"),
             (None, ""), ({"Type": "NONSENSE", "Day": 3}, "")]
    for sales, text in cases:
        assert xr.terms_text(sales) == text, (sales, text)
        if text:
            assert xr.terms_for_xero(text) == {"Day": sales["Day"], "Type": sales["Type"]}


def test_terms_the_app_cannot_say_in_xero_are_left_to_xero():
    assert xr.terms_for_xero("Prepaid") == {"Day": 0, "Type": "DAYSAFTERBILLDATE"}
    assert xr.terms_for_xero("whenever") is None and xr.terms_for_xero("") is None


def test_a_contact_without_terms_of_its_own_is_on_xeros_default():
    read = {"contacts": [{"id": "A", "PaymentTerms": {"Type": "DAYSAFTERBILLDATE", "Day": 7}},
                         {"id": "B", "PaymentTerms": None}],
            "default_terms": {"Type": "OFFOLLOWINGMONTH", "Day": 20}}
    assert xr.terms_by_contact(read) == {"A": "Net 7", "B": "20th of the following month"}
    assert xr.terms_by_contact({"contacts": [{"id": "C"}]}) == {}


def test_a_contact_made_in_xero_carries_everything_the_app_knows():
    c = xr.contact_payload(CUSTOMER)
    assert c["Name"] == "Bells Creek Pty Ltd"
    assert c["EmailAddress"] == "accounts@bells.example"
    assert (c["FirstName"], c["LastName"]) == ("Jo", "Smith")
    assert c["TaxNumber"] == "12345678901"
    assert c["Phones"] == [{"PhoneType": "DEFAULT", "PhoneNumber": "07 5555 1234"}]
    assert [a["AddressType"] for a in c["Addresses"]] == ["STREET", "POBOX"]
    assert c["Addresses"][0]["City"] == "Caloundra" and c["Addresses"][1]["PostalCode"] == "4551"
    assert c["PaymentTerms"] == {"Sales": {"Day": 30, "Type": "DAYSAFTERBILLDATE"}}


def test_a_customer_with_little_on_file_makes_a_small_contact():
    c = xr.contact_payload({"name": "Walk-in", "billing_same": False,
                            "billing_address1": "PO Box 9", "billing_city": "Logan"})
    assert c == {"Name": "Walk-in", "Addresses": [{
        "AddressType": "POBOX", "AddressLine1": "PO Box 9", "AddressLine2": "",
        "City": "Logan", "Region": "", "PostalCode": "", "Country": "Australia"}]}


def test_only_what_the_xero_contact_is_missing_is_filled_in():
    existing = {"EmailAddress": "ap@bells.example", "FirstName": "", "LastName": "",
                "TaxNumber": "", "Phones": [{"PhoneType": "DEFAULT", "PhoneNumber": ""}],
                "Addresses": [{"AddressType": "POBOX", "AddressLine1": "PO Box 1"}],
                "PaymentTerms": {"Type": "DAYSAFTERBILLDATE", "Day": 14}}
    patch, filled = xr.contact_gaps(existing, CUSTOMER)
    assert "EmailAddress" not in patch and "PaymentTerms" not in patch
    assert patch["FirstName"] == "Jo" and patch["TaxNumber"] == "12345678901"
    assert patch["Phones"][0]["PhoneNumber"] == "07 5555 1234"
    assert [a["AddressType"] for a in patch["Addresses"]] == ["STREET"]
    assert filled == ["contact person", "ABN", "phone", "delivery address"]


def test_a_complete_xero_contact_is_left_alone():
    full = dict(xr.contact_payload(CUSTOMER), FirstName="Al", LastName="B",
                PaymentTerms={"Type": "DAYSAFTERBILLDATE", "Day": 7})
    assert xr.contact_gaps(full, CUSTOMER) == ({}, [])
