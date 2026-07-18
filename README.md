# TAF Order Entry

Desktop order-entry and worksheet/PDF generator for **Total Air Filtration** —
a Windows Tkinter app backed by Supabase (auth + shared database).

Staff create filter / bag orders, the app generates printable worksheets and
order PDFs, and everything is stored centrally with per-user roles, an audit
log, stock management and a customer database.

> **Version 2.0.0** — TAF-brand UI (Public Sans, rounded navy-header cards,
> pill buttons, Filter/Bags/Mixed type badges, split-panel login).

---

## Features

- **New Order** — filter & bag/roll line items, dedicated compressor-filter
  presets, live worksheet + order-PDF generation.
- **Previous Orders** — search / filter, reload, duplicate, regenerate, status
  tracking, priority flags, notes, per-order history.
- **Dashboard** — orders-per-week, order-type and busiest-customer charts, low
  stock alerts.
- **Stock** — items with images, on-hand / minimum levels, adjustments & history.
- **Customers** — full customer database with delivery/billing details.
- **Audit Log** — every significant action recorded.
- **Settings** — media types, low-stock thresholds, user management, light/dark
  mode, change password, in-app software update.

## Tech stack

Python 3.11+ · Tkinter · Supabase (Postgres + Auth) · ReportLab · openpyxl /
python-docx (+ Excel/Word COM via pywin32) · Pillow · tkcalendar · PyInstaller.

---

## Prerequisites

- **Windows** (Excel & Word are used via COM for some worksheet templates).
- **Python 3.11+**.
- A **Supabase project** (free tier is fine).

## Setup

```bash
# 1. Clone
git clone https://github.com/<you>/<repo>.git
cd <repo>

# 2. (recommended) virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Configure Supabase

1. Set your project URL in [`taf_order_app/db.py`](taf_order_app/db.py) —
   the `SUPABASE_URL` constant near the top.
2. Copy the settings template and add your **anon / publishable** key:
   ```bash
   copy settings.example.json settings.json
   ```
   ```json
   {
     "custom_media_types": [],
     "supabase_anon_key": "sb_publishable_xxxxxxxxxxxxxxxxx"
   }
   ```
   `settings.json` is git-ignored so your key is never committed.

### Create the database tables

In the Supabase dashboard → **SQL Editor**, run these once (in order):

1. `setup_database.sql` — profiles + orders + core RPCs
2. `customers_schema.sql`
3. `stock_schema.sql`
4. `extra_columns_migration.sql`
5. The `migrate_*.sql` files (audit log, media types, stock alerts, updater,
   user management) — run any that apply to bring an existing DB up to date.

### Create the first admin account

```bash
python create_default_account.py
```

Credentials are read from environment variables (or prompted if unset):

```bash
set TAF_ADMIN_EMAIL=you@example.com
set TAF_ADMIN_PASSWORD=your-strong-password
set TAF_ADMIN_NAME=Your Name
set TAF_ADMIN_ROLE=Director
```

---

## Run from source

```bash
python modern_order_gui.py
```

## Build the Windows executable

```bash
pyinstaller --noconfirm --clean TAFOrderEntry.spec
```

Output lands in `dist/TAFOrderEntry/` (onedir build; run `TAFOrderEntry.exe`).
Public Sans fonts and the logos are bundled automatically.

### Build the installer (optional)

Install [Inno Setup 6](https://jrsoftware.org/isinfo.php), then:

```bash
ISCC installer.iss
```

Produces `TAFOrderEntry_Setup.exe`.

---

## Project structure

```
modern_order_gui.py        Main UI (app shell, all tabs, widgets)
pdf_generator.py           Order-PDF generation (ReportLab)
template_filler.py         Excel worksheet filling (COM)
taf_order_app/
  db.py                    Supabase wrapper (auth, orders, stock, customers)
  login_window.py          Split-panel login / register / reset
  order_service.py         Order build/save orchestration
  bag_filler.py            Word worksheet filling (COM)
  updater.py               In-app auto-update (APP_VERSION lives here)
  user_management.py       Roles & user admin
  models.py / validation.py
fonts/                     Bundled Public Sans (OFL)
*.sql                      Schema + migrations
TAFOrderEntry.spec         PyInstaller build spec
installer.iss              Inno Setup installer script
```

## Working from anywhere (incl. your phone)

The whole release pipeline is cloud-based — you can edit code and ship updates
without a PC.

**Edit code:** open the repo on github.com and edit files inline, or press `.`
to open the browser VS Code editor (`github.dev`), or use the **GitHub mobile
app**. Commit straight to `main`.

**Cut a release (one button):** repo → **Actions** tab → **Build & Release** →
**Run workflow** → type the version (e.g. `2.0.3`) and optional notes → **Run**.
GitHub bumps the version, builds the Windows installer, and publishes the
Release. Installed clients then auto-update.

> ⚠️ A published release auto-updates **all** users immediately, and you can't
> run/test the Windows app on a phone. CI runs a syntax check before building
> (so a broken commit won't ship), but it can't catch logic bugs — test bigger
> changes on a Windows PC (install the release's `TAFOrderEntry_Setup.exe`)
> before relying on them.

## Notes

- **Roles:** Director / Admin > Manager > Employee gate destructive actions and
  user management.
- **Auto-update:** the app checks the latest **GitHub Release** of this repo and
  self-updates by downloading and silently running the installer. To ship an
  update, run `python push_update.py 2.0.1 "release notes"` — it bumps the
  version, tags `v2.0.1`, and pushes; GitHub Actions then builds the installer
  and publishes the release. Requires the repo to be **public** (so the updater
  can read releases without a token) and the `SUPABASE_ANON_KEY` Actions secret.
- **Fonts:** Public Sans is bundled under the SIL Open Font License.
