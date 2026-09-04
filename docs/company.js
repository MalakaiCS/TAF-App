/*
  Total Air Filtration — the details shown on every customer-facing page.

  ────────────────────────────────────────────────────────────────────────
  FILL THESE IN. Edit this one file on github.com and save; the pages pick
  it up straight away. No release, no rebuild.
  ────────────────────────────────────────────────────────────────────────

  Anything left blank is simply not shown — a page never prints an empty
  label or a placeholder, so a half-filled file still looks right. But a
  customer being asked to accept a quote with no phone number to ring is the
  thing worth fixing first.

  This is loaded as a plain script rather than fetched from the database on
  purpose: the moment these details matter most is when a link is broken or
  expired, and at that point there is no token and nothing to fetch with.
*/
window.TAF_COMPANY = {
  name:    "Total Air Filtration",

  // Rung, emailed and posted. Put the numbers customers should actually use.
  phone:   "07 3800 3448",              // e.g. "07 3800 0000"
  email:   "sales@totalairfiltration.com.au",              // e.g. "sales@totalairfiltration.com.au"
  website: "https://totalairfiltration.com.au",              // e.g. "https://totalairfiltration.com.au"
  abn:     "",              // e.g. "12 345 678 901"

  // Where post goes.
  address: "Unit 1/19 Tradelink Road, hillcrest QLD 4118",              // e.g. "19 Trade Link Road, Hillcrest QLD 4118"

  // Where customers collect an order marked "Ready for pick up", and when.
  // Shown on exactly those orders, which is where it is actually needed.
  pickup: {
    address: "Unit 1/19 Tradelink Road, hillcrest QLD 4118",            // e.g. "19 Trade Link Road, Hillcrest QLD 4118"
    hours:   "Monday to Thursday 7am to 3:30pm & Friday 7am to 12:30pm",            // e.g. "Monday to Friday, 7am - 3.30pm"
    note:    "Ask at the front office and quote your order number."             // e.g. "Ask at the front office and quote your order number."
  },

  // Trading hours shown in the footer.
  hours: "Monday to Thursday 7am to 3:30pm & Friday 7am to 12:30pm"                 // e.g. "Monday to Friday, 7am - 4pm"
};
