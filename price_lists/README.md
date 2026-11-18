# Price lists

The priced catalogue, as imported into Xero and into the app.

Import them under **Settings → Pricing → Import Price Files** (select all
three at once). Re-importing is safe: a part number already in the list is
updated to the price in the file, and nothing else is touched.

## What they cover

|                | |
| -------------- | - |
| Rows           | 12,480 (4,160 per file) |
| Types          | Flat Panel (`FPF`), V-form / pleated panel (`PPF`) |
| Media          | G4, F5, F6, F7, F8, 180, Washable (`W`), Carbon (`CARB`) |
| Thickness      | 10mm to 200mm, in 5mm steps |
| Area           | 0.1 m² to 2.0 m², in 0.1 m² steps |
| Prices         | $24.00 to $545.00, ex GST |

## The part-number shape

The item code in these files is exactly what the app builds for a line, so a
quote finds the price without anything being matched up by hand:

```
FPF   G4     25      -020        Flat panel, G4 media, 25mm, 0.2 m²
PPF   CARB   50      -1.8        V-form, carbon, 50mm, 1.8 m²
```

Note the area changes shape at 1 m²: `010` … `090`, then `1.0` … `2.0`. That
is what the catalogue does, so it is what `part_numbers.sqm_suffix` does.

## What is *not* priced here

Quoting a line of any of these will show it as "to be confirmed" rather than
guessing, and the quote will say why:

- **Stepped filters** (`STPPFW50-…`) and **flyscreens** (`FPF09-…`) — no rows
  in the catalogue at all.
- **Thicknesses that aren't a multiple of 5** — a 48mm V-form is common on
  purchase orders and has no row; 45mm and 50mm do.
- **Anything over 2.0 m²**.
- **Bag filters and media rolls** — they have their own codes.

To cover a gap, either add the rows to a spreadsheet and re-import, or set a
**rate per m²** for that filter type and media under Settings → Pricing,
which is used wherever a part number has no listed price.
