"""The database's own rules, checked against a real Postgres.

Everything else in this project tests the apps. But the rules that actually
matter for supply requests and the bell are not in any app - they are
row-level security policies and triggers in migrate_supply_requests.sql, and
the apps are deliberately trusted with none of them. A test that stubbed the
database would be testing a stub.

So this starts a throwaway Postgres, puts in just enough of Supabase to run
the real migration (the auth.uid() function, the two roles, a profiles table,
and is_staff()/is_manager() exactly as migrate_staff_access.sql defines
them), runs the migration twice, and then acts as each kind of person:
somebody on the floor, a manager, a director, and somebody who has registered
but was never approved.

Run:  python tests/db_rules.py
Needs the PostgreSQL server binaries (initdb, pg_ctl) and psql. GitHub's
Ubuntu runners have them. Skips cleanly anywhere that does not.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "migrate_supply_requests.sql"

DAVE = "00000000-0000-0000-0000-00000000000a"      # on the floor
SARAH = "00000000-0000-0000-0000-00000000000b"     # manager
KAI = "00000000-0000-0000-0000-00000000000c"       # director
AMY = "00000000-0000-0000-0000-00000000000d"       # admin
STRANGER = "00000000-0000-0000-0000-00000000000e"  # "Manager", never approved

SHIM = f"""
CREATE EXTENSION IF NOT EXISTS pgcrypto;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon')
     THEN CREATE ROLE anon NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated')
     THEN CREATE ROLE authenticated NOLOGIN; END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS auth;
-- Supabase reads the signed-in user off the request; here it is a setting.
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
GRANT USAGE ON SCHEMA auth TO anon, authenticated;
GRANT EXECUTE ON FUNCTION auth.uid() TO anon, authenticated;

CREATE TABLE public.profiles (
  id uuid PRIMARY KEY, full_name text, username text, role text,
  approved boolean NOT NULL DEFAULT false);
-- Supabase grants everything on public tables; row-level security is the
-- gate. The same here, or a "permission denied" would pass for the wrong
-- reason.
GRANT USAGE ON SCHEMA public TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated;
GRANT ALL ON public.profiles TO anon, authenticated;

-- Exactly as migrate_staff_access.sql defines them.
CREATE OR REPLACE FUNCTION public.is_staff() RETURNS boolean LANGUAGE sql
STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT EXISTS (SELECT 1 FROM public.profiles
                  WHERE id = auth.uid() AND approved = true); $$;
CREATE OR REPLACE FUNCTION public.is_manager() RETURNS boolean LANGUAGE sql
STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT EXISTS (SELECT 1 FROM public.profiles
                  WHERE id = auth.uid() AND approved = true
                    AND role IN ('Director','Admin','Manager')); $$;
GRANT EXECUTE ON FUNCTION public.is_staff(), public.is_manager() TO authenticated;

INSERT INTO public.profiles VALUES
 ('{DAVE}',     'Dave Floor', 'dave',  'Employee', true),
 ('{SARAH}',    'Sarah Boss', 'sarah', 'Manager',  true),
 ('{KAI}',      'Kai Brown',  'kai',   'Director', true),
 ('{AMY}',      'Amy Admin',  'amy',   'Admin',    true),
 ('{STRANGER}', 'Stranger',   'who',   'Manager',  false);
"""

FAILURES: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}" + (f"\n        {detail}" if detail else ""))
        FAILURES.append(label)


# ── A throwaway Postgres ─────────────────────────────────────────────────────

def _bin(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for path in sorted(glob.glob(f"/usr/lib/postgresql/*/bin/{name}"),
                       reverse=True):
        return path
    return ""


class Postgres:
    """initdb into a temporary folder, listening only on a socket there."""

    PORT = "55439"

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="taf-pg-")
        self.data = os.path.join(self.dir, "data")
        # initdb refuses to run as root. On a build runner this is a normal
        # user already; in a container it is not, and postgres is.
        self.as_postgres = hasattr(os, "geteuid") and os.geteuid() == 0
        if self.as_postgres:
            shutil.chown(self.dir, "postgres", "postgres")

    def _run(self, *cmd):
        if self.as_postgres:
            cmd = ("runuser", "-u", "postgres", "--") + cmd
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    def start(self) -> bool:
        r = self._run(_bin("initdb"), "-D", self.data, "-A", "trust",
                      "-U", "postgres")
        if r.returncode:
            print(r.stdout, r.stderr)
            return False
        r = self._run(_bin("pg_ctl"), "-D", self.data, "-w", "-l",
                      os.path.join(self.dir, "log"), "-o",
                      f"-p {self.PORT} -k {self.dir} -c listen_addresses=",
                      "start")
        if r.returncode:
            print(r.stdout, r.stderr)
            return False
        return True

    def stop(self) -> None:
        self._run(_bin("pg_ctl"), "-D", self.data, "-m", "immediate", "stop")
        shutil.rmtree(self.dir, ignore_errors=True)

    def psql(self, sql: str, db: str = "postgres"):
        """Run some SQL; return (ok, stdout, stderr). Stops at the first error."""
        r = subprocess.run(
            [_bin("psql"), "-X", "-q", "-tA", "-h", self.dir, "-p", self.PORT,
             "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1"],
            input=sql, capture_output=True, text=True, timeout=120)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()

    def fresh(self) -> None:
        """A new database with the shim and the migration in it."""
        self.psql("DROP DATABASE IF EXISTS t;")
        self.psql("CREATE DATABASE t;")
        ok, _o, err = self.psql(SHIM, "t")
        assert ok, f"the stand-in for Supabase did not load: {err}"
        ok, _o, err = self.psql(MIGRATION.read_text(encoding="utf-8"), "t")
        assert ok, f"the migration did not run: {err}"

    def as_(self, who: str, sql: str):
        """Run as a signed-in person, the way a request from an app does."""
        return self.psql(
            "SET ROLE authenticated;\n"
            f"SELECT set_config('request.jwt.claim.sub', '{who}', false) "
            "\\g /dev/null\n" + sql, "t")

    def admin(self, sql: str) -> str:
        """Look at the real state of things, past row-level security."""
        ok, out, err = self.psql(sql, "t")
        assert ok, err
        return out


# ── The checks ───────────────────────────────────────────────────────────────

def ask(pg: Postgres, who: str, item="Tape", detail="50mm foil",
        qty="3 rolls", urgent=False, note="", ref="NULL"):
    ref = "NULL" if ref == "NULL" else f"'{ref}'"
    return pg.as_(who, f"SELECT id FROM request_supply('{item}', '{detail}', "
                       f"'{qty}', {str(urgent).lower()}, '{note}', {ref});")


def run_checks(pg: Postgres) -> None:
    # ── Setting it up ────────────────────────────────────────────────────
    pg.fresh()
    ok, _o, err = pg.psql(MIGRATION.read_text(encoding="utf-8"), "t")
    check("the migration can be run a second time", ok, err)

    pg.psql("DROP DATABASE IF EXISTS early;")
    pg.psql("CREATE DATABASE early;")
    ok, _o, err = pg.psql(MIGRATION.read_text(encoding="utf-8"), "early")
    check("run before migrate_staff_access.sql, it says so plainly",
          not ok and "migrate_staff_access.sql" in err, err)

    # ── Who asked ────────────────────────────────────────────────────────
    pg.fresh()
    ok, _o, err = pg.as_(DAVE, f"""
        INSERT INTO supply_requests (item, detail, quantity, requested_by,
                                     requested_by_name, status)
        VALUES ('Tape', 'foil', '3', '{KAI}', 'Kai Brown', 'received');""")
    row = pg.admin("SELECT requested_by || '|' || requested_by_name || '|' "
                   "|| status FROM supply_requests;")
    check("somebody asking as somebody else is written down as themselves",
          row == f"{DAVE}|Dave Floor|open", row)

    # ── Who is told ──────────────────────────────────────────────────────
    pg.fresh()
    ask(pg, DAVE, urgent=True, note="bench 2")
    told = pg.admin("SELECT string_agg(p.full_name, ',' ORDER BY p.full_name) "
                    "FROM notifications n JOIN profiles p ON p.id = n.recipient;")
    check("every approved manager, admin and director is told",
          told == "Amy Admin,Kai Brown,Sarah Boss", told)
    check("somebody on the floor is not told", "Dave" not in told, told)
    check("an unapproved account with a Manager role is not told",
          "Stranger" not in told, told)
    title = pg.admin("SELECT title FROM notifications LIMIT 1;")
    check("an urgent request says so first", title.startswith("URGENT: Tape"),
          title)

    pg.fresh()
    ask(pg, KAI, item="Rivets", detail="", qty="1 box")
    told = pg.admin("SELECT string_agg(p.full_name, ',' ORDER BY p.full_name) "
                    "FROM notifications n JOIN profiles p ON p.id = n.recipient;")
    check("a manager asking is not told about their own request",
          told == "Amy Admin,Sarah Boss", told)

    # ── Nobody writes in anybody's bell ──────────────────────────────────
    pg.fresh()
    ok, _o, err = pg.as_(DAVE, f"INSERT INTO notifications (recipient, kind, "
                               f"title) VALUES ('{KAI}', 'x', 'Pay rise');")
    check("nobody can put a notification in somebody else's bell",
          not ok and "permission denied" in err, err)
    ok, _o, err = pg.as_(SARAH, "INSERT INTO notifications (recipient, kind, "
                                f"title) VALUES ('{SARAH}', 'x', 'mine');")
    check("not even in their own", not ok and "permission denied" in err, err)

    ask(pg, DAVE)
    ok, _o, err = pg.as_(SARAH, "UPDATE notifications SET title = 'forged';")
    check("a notification's words cannot be rewritten",
          not ok and "permission denied" in err, err)
    ok, out, err = pg.as_(SARAH, "SELECT count(*) FROM notifications;")
    check("a manager sees only their own notifications", ok and out == "1",
          out or err)
    ok, out, err = pg.as_(DAVE, "SELECT my_unread_count();")
    check("somebody on the floor has an empty bell", ok and out == "0",
          out or err)

    # ── Moving a request along ───────────────────────────────────────────
    pg.fresh()
    ask(pg, DAVE)
    ok, _o, err = pg.as_(DAVE, "UPDATE supply_requests SET status = 'received';")
    check("the person who asked cannot mark it received",
          not ok and "row-level security" in err, err)

    ok, _o, err = pg.as_(SARAH, "UPDATE supply_requests SET status = 'ordered';")
    row = pg.admin("SELECT status || '|' || handled_by_name FROM supply_requests;")
    check("a manager marks it ordered, and is written down as having done it",
          ok and row == "ordered|Sarah Boss", row or err)
    left = pg.admin("SELECT count(*) FROM notifications WHERE read_at IS NULL;")
    check("once one manager deals with it, every manager's bell clears",
          left == "0", left)

    ok, out, _e = pg.as_(DAVE, "UPDATE supply_requests SET status = 'cancelled' "
                               "RETURNING id;")
    check("once it is ordered, the person who asked cannot cancel it",
          out == "", out)

    pg.fresh()
    ask(pg, DAVE)
    ok, out, err = pg.as_(DAVE, "UPDATE supply_requests SET quantity = "
                                "'5 rolls' RETURNING quantity;")
    check("the person who asked can change it while nothing has happened",
          ok and out == "5 rolls", out or err)
    ok, _o, err = pg.as_(DAVE, "UPDATE supply_requests SET status = 'cancelled';")
    left = pg.admin("SELECT count(*) FROM notifications WHERE read_at IS NULL;")
    check("cancelling it clears the managers' bells too",
          ok and left == "0", left or err)

    ok, out, err = pg.as_(AMY, "UPDATE supply_requests SET requested_by_name = "
                               "'Somebody Else' RETURNING requested_by_name;")
    check("who asked cannot be rewritten afterwards, even by a manager",
          ok and out == "Dave Floor", out or err)

    # ── Sent twice ───────────────────────────────────────────────────────
    pg.fresh()
    answers = [ask(pg, DAVE, ref="phone-abc-1") for _ in range(3)]
    n = pg.admin("SELECT count(*) FROM supply_requests;")
    told = pg.admin("SELECT count(*) FROM notifications;")
    check("the same request sent three times is filed once", n == "1", n)
    # Counting rows is not enough. A unique index alone would also leave one
    # row - by refusing the retries with an error. On a phone the queue reads
    # that as "the database said no" and tells the person their request
    # failed, when it went through. A retry has to be answered as a success,
    # with the request it already filed.
    ids = {out for ok, out, _e in answers}
    check("a retry is answered as a success, with the request already filed",
          all(ok for ok, _o, _e in answers) and len(ids) == 1,
          "; ".join(err or out for _ok, out, err in answers))
    check("and every manager is told once, not three times", told == "3", told)
    ask(pg, DAVE, ref="phone-abc-2")
    n = pg.admin("SELECT count(*) FROM supply_requests;")
    check("a different request is still a new one", n == "2", n)

    # ── What cannot be asked ─────────────────────────────────────────────
    pg.fresh()
    ok, _o, err = ask(pg, DAVE, item="Other", detail="")
    check("\"Other\" with nothing said is refused",
          not ok and "other_says_what_it_is" in err, err)
    ok, _o, err = ask(pg, STRANGER)
    check("an account nobody approved cannot ask for anything",
          not ok and "row-level security" in err, err)

    # ── The bell's own calls ─────────────────────────────────────────────
    pg.fresh()
    ask(pg, DAVE, ref="a")
    ask(pg, DAVE, item="Rivets", detail="", ref="b")
    ok, out, _e = pg.as_(SARAH, "SELECT my_unread_count();")
    check("the count is the number unread", out == "2", out)
    ok, out, _e = pg.as_(SARAH, "SELECT mark_notifications_read(NULL);")
    ok, after, _e = pg.as_(SARAH, "SELECT my_unread_count();")
    check("marking all read empties the bell", out == "2" and after == "0",
          f"{out} then {after}")
    ok, out, _e = pg.as_(KAI, "SELECT my_unread_count();")
    check("and only that person's bell", out == "2", out)



# ── Calculator settings and merging customers ──────────────────────────────
# These run on the REAL schema: every migration in the documented order, so
# the merge is tested against the orders, quotes, sites and prices tables as
# they actually are rather than a guess at them. The three that need
# Supabase Storage are left out; nothing here touches storage.

MERGE_MIGRATION = ROOT / "migrate_packing_and_merge.sql"
NEEDS_STORAGE = {"migrate_po_inbox.sql", "migrate_avatars.sql",
                 "migrate_order_files.sql", "migrate_stock_images.sql"}

A = "10000000-0000-0000-0000-00000000000a"    # stays: CAS - Tweed Heads
B = "10000000-0000-0000-0000-00000000000b"    # duplicate of A
C = "10000000-0000-0000-0000-00000000000c"    # a different company
D = "10000000-0000-0000-0000-00000000000d"    # another branch of A's company
E = "10000000-0000-0000-0000-00000000000e"    # a second duplicate of A


def full_schema(pg: Postgres, db: str = "f") -> None:
    sys.path.insert(0, str(ROOT / "tests"))
    from test_migrations import ORDER
    pg.psql(f"DROP DATABASE IF EXISTS {db};")
    pg.psql(f"CREATE DATABASE {db};")
    shim = SHIM.replace(
        "CREATE TABLE public.profiles (",
        "CREATE TABLE auth.users (id uuid PRIMARY KEY, email text, "
        "raw_user_meta_data jsonb);\nCREATE TABLE public.profiles (")
    ok, _o, err = pg.psql(shim, db)
    assert ok, err
    for name in ORDER:
        if name in NEEDS_STORAGE:
            continue
        ok, _o, err = pg.psql((ROOT / name).read_text(encoding="utf-8"), db)
        assert ok, f"{name} did not load: {err}"
    # migrate_staff_access.sql approves everybody already there when it runs,
    # so the people who work here are not locked out on the day. That
    # includes the stranger the shim made earlier - who has to be a stranger
    # again for the checks to mean anything.
    ok, _o, err = pg.psql(f"UPDATE profiles SET approved = false "
                          f"WHERE id = '{STRANGER}';", db)
    assert ok, err


def as_in(pg: Postgres, db: str, who: str, sql: str):
    return pg.psql("SET ROLE authenticated;\n"
                   f"SELECT set_config('request.jwt.claim.sub', '{who}', "
                   "false) \\g /dev/null\n" + sql, db)


def q(pg: Postgres, sql: str, db: str = "f") -> str:
    ok, out, err = pg.psql(sql, db)
    assert ok, err
    return out


FIXTURES = f"""
INSERT INTO auth.users (id) SELECT id FROM profiles ON CONFLICT DO NOTHING;
INSERT INTO customers (id, name, short_name, legal_name, abn, payment_terms,
                       delivery_address1, delivery_city, delivery_state,
                       delivery_postcode, po_aliases, updated_at) VALUES
 ('{A}', 'CAS - Tweed Heads', 'CAS Tweed', 'Complete Air Supply Pty Ltd',
  '11 111 111 111', 'Net 30', '3A/38 Enterprise Avenue', 'Tweed Heads',
  'NSW', '2486', '["CAS TWEED HEADS"]', '2026-10-01 09:00+10'),
 ('{B}', 'Complete Air Supply Tweed', '', 'Complete Air Supply Pty Ltd',
  '', 'Net 30', 'Rear 40 Enterprise Avenue', 'Tweed Heads', 'NSW', '2486',
  '["COMPLETE AIR TWEED"]', '2026-10-01 09:00+10'),
 ('{C}', 'Total Comfort Air', '', 'Total Comfort Pty Ltd', '22 222 222 222',
  'COD', '1 Other St', 'Logan', 'QLD', '4114', '[]', '2026-10-01 09:00+10'),
 ('{D}', 'CAS - Bells Creek', 'CAS Bells', 'Complete Air Supply Pty Ltd',
  '11 111 111 111', 'Net 30', '19 Fred Chaplin Cct', 'Bells Creek', 'QLD',
  '4551', '[]', '2026-10-01 09:00+10'),
 ('{E}', 'C.A.S. Tweed (old)', '', '', '', '', '3A/38 Enterprise Avenue',
  'Tweed Heads', 'NSW', '2486', '[]', '2026-10-01 09:00+10');

INSERT INTO orders (id, user_id, customer_name, order_number, header, items)
SELECT gen_random_uuid(), '{DAVE}', n, o,
       jsonb_build_object('Customer Name', n, 'Order Number', o),
       '[]'::jsonb
  FROM (VALUES ('CAS Tweed', 'A-1'), ('CAS - Tweed Heads', 'A-2'),
               ('cas tweed ', 'A-3'),
               ('Complete Air Supply Tweed', 'B-1'),
               ('COMPLETE AIR SUPPLY TWEED', 'B-2'),
               ('C.A.S. Tweed (old)', 'E-1'),
               ('Total Comfort Air', 'C-1'), ('CAS Bells', 'D-1')) v(n, o);

INSERT INTO quotes (quote_number, customer_id, customer_name, total, status)
VALUES ('Q-1', '{B}', 'Complete Air Supply Tweed', 1234.50, 'sent'),
       ('Q-2', NULL, 'CAS Tweed', 100.25, 'accepted'),
       ('Q-3', '{C}', 'Total Comfort Air', 77.00, 'sent');

INSERT INTO customer_prices (customer_id, part_number, unit_price) VALUES
 ('{A}', 'FPFG425-040', 10.00), ('{B}', 'FPFG425-040', 9.50),
 ('{B}', 'PPFG450-060', 5.00), ('{C}', 'FPFG425-040', 8.00);

INSERT INTO sites (customer_name, name, location)
VALUES ('Complete Air Supply Tweed', 'Plant room 2', 'Level 3');
INSERT INTO returns (customer_name, order_number, reason)
VALUES ('Complete Air Supply Tweed', 'B-1', 'Wrong size');
INSERT INTO recurring_jobs (customer_name, every_months, job, next_due)
VALUES ('Complete Air Supply Tweed', 6, 'AHU service', '2027-01-01');
"""

GOOD = {"set": {"name": "CAS - Tweed Heads", "payment_terms": "Net 30"},
        "prices": {"FPFG425-040": "survivor"}}


def merge_sql(req: str, survivor: str, merged, decisions=None,
              expected="NULL") -> str:
    import json as _json
    ids = "ARRAY[" + ",".join(f"'{m}'::uuid" for m in merged) + "]"
    dec = _json.dumps(decisions if decisions is not None else GOOD)
    return (f"SELECT merge_customers('{req}', '{survivor}', {ids}, "
            f"'{dec}'::jsonb, {expected});")


def snapshot(pg: Postgres) -> str:
    return q(pg, "SELECT string_agg(order_number || '=' || customer_name || "
                 "'/' || COALESCE(customer_id::text, '-'), ',' ORDER BY "
                 "order_number) FROM orders;")


def run_merge_checks(pg: Postgres) -> None:
    print("\n── calculator settings ──")
    full_schema(pg)
    ok, _o, err = pg.psql(MERGE_MIGRATION.read_text(encoding="utf-8"), "f")
    check("the migration runs on the real schema, twice over", ok, err)
    addr = q(pg, "SELECT value ->> 'base_address' FROM calc_settings "
                 "WHERE key = 'company';")
    check("the base address starts as supplied",
          addr == "Unit 1/19 Tradelink Road, Hillcrest Queensland 4118 "
                  "Australia", addr)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT set_calc_setting('company', "
                         "'{\"base_address\": \"Somewhere else\"}');")
    check("somebody on the floor cannot change a setting",
          not ok and "row-level security" in err, err)
    ok, out, err = as_in(pg, "f", SARAH, "SELECT set_calc_setting('company', "
                         "'{\"base_address\": \"2 New Road, Logan QLD 4114\"}');")
    check("a manager can, and the version moves on", ok and out == "2",
          out or err)
    ok, out, err = as_in(pg, "f", SARAH, "SELECT set_calc_setting('packing', "
                         "'{}');")
    check("only known sections can be stored", not ok, err)
    ok, out, err = as_in(pg, "f", SARAH, "SELECT set_calc_setting("
                         "'c_channel', '{\"estimate_rule\": "
                         "{\"subtract_mm\": 3}}');")
    check("a manager can save the C-channel settings", ok and out == "1",
          out or err)
    ok, _o, err = as_in(pg, "f", DAVE, "SELECT set_calc_setting("
                        "'c_channel', '{}');")
    check("and somebody on the floor cannot", not ok, err)
    ok, _o, err = pg.psql((ROOT / "migrate_c_channel.sql").read_text(
        encoding="utf-8"), "f")
    kept = q(pg, "SELECT value -> 'estimate_rule' ->> 'subtract_mm' FROM "
                 "calc_settings WHERE key = 'c_channel';")
    check("re-running step 34 keeps what was saved", ok and kept == "3",
          kept or err)
    ok, out, err = as_in(pg, "f", SARAH, "SELECT set_calc_setting("
                         "'delivery_labels', '{\"enabled\": false}');")
    check("a manager can switch delivery labels off for everyone",
          ok and out == "1", out or err)
    ok, _o, err = as_in(pg, "f", DAVE, "SELECT set_calc_setting("
                        "'delivery_labels', '{\"enabled\": true}');")
    check("and somebody on the floor cannot switch them back", not ok, err)
    default = q(pg, "SELECT bool_and(delivery_labels) FROM customers;")
    check("every customer starts with delivery labels on",
          default in ("t", ""), default)
    for name in ("migrate_label_switches.sql", "migrate_c_channel.sql",
                 "migrate_label_switches.sql"):
        ok, _o, err = pg.psql((ROOT / name).read_text(encoding="utf-8"), "f")
        if not ok:
            break
    still = q(pg, "SELECT value ->> 'enabled' FROM calc_settings "
                  "WHERE key = 'delivery_labels';")
    check("steps 34 and 35 re-run in any order without losing the switch",
          ok and still == "false", still or err)
    hist = q(pg, "SELECT string_agg(version || ':' || changed_by || ':' || "
                 "(value ->> 'base_address'), '|' ORDER BY version) FROM "
                 "calc_settings_history WHERE key = 'company';")
    check("every version is kept, with who made it",
          hist.startswith("1::Unit 1/19") and
          hist.endswith("2:Sarah Boss:2 New Road, Logan QLD 4114"), hist)
    ok, _o, err = as_in(pg, "f", SARAH, "INSERT INTO calc_settings_history "
                        "(key, version, value) VALUES ('company', 9, '{}');")
    check("history cannot be written by hand", not ok, err)
    ok, _o, err = as_in(pg, "f", SARAH, "DELETE FROM calc_settings;")
    check("settings cannot be deleted", not ok, err)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT value ->> 'base_address' "
                         "FROM calc_settings WHERE key = 'company';")
    check("everyone on staff reads the current one",
          out == "2 New Road, Logan QLD 4114", out or err)
    pg.psql(MERGE_MIGRATION.read_text(encoding="utf-8"), "f")
    addr = q(pg, "SELECT value ->> 'base_address' FROM calc_settings "
                 "WHERE key = 'company';")
    check("re-running the migration keeps the changed address",
          addr == "2 New Road, Logan QLD 4114", addr)

    print("\n── merging customer accounts ──")
    ok, _o, err = pg.psql(FIXTURES, "f")
    assert ok, err
    before = snapshot(pg)
    totals_before = q(pg, "SELECT sum(total) FROM quotes;")

    ok, _o, err = as_in(pg, "f", DAVE, merge_sql("r0", A, [B]))
    check("somebody on the floor cannot merge accounts",
          not ok and "Only a manager" in err, err)
    ok, _o, err = as_in(pg, "f", STRANGER, merge_sql("r0", A, [B]))
    check("nor can an unapproved account calling itself a manager",
          not ok and "Only a manager" in err, err)
    ok, _o, err = as_in(pg, "f", SARAH, merge_sql("r0", A, [A]))
    check("an account cannot be merged into itself",
          not ok and "into itself" in err, err)
    ok, _o, err = as_in(pg, "f", SARAH, merge_sql("r0", A, [B, B]))
    check("or listed twice", not ok and "twice" in err, err)
    ok, _o, err = as_in(pg, "f", SARAH, merge_sql(
        "r0", A, [B], {"set": {"name": "CAS - Tweed Heads"}}))
    check("a price both accounts have must be chosen, not defaulted",
          not ok and "FPFG425-040" in err, err)
    check("and a refused merge changes nothing", snapshot(pg) == before)
    ok, _o, err = as_in(pg, "f", SARAH, merge_sql(
        "r0", A, [B], {"prices": {"FPFG425-040": "survivor"}}))
    check("the company name to keep has to be chosen",
          not ok and "company name" in err, err)
    ok, _o, err = as_in(pg, "f", SARAH, merge_sql("r0", A, [C], {
        "set": {"name": "CAS - Tweed Heads"},
        "prices": {"FPFG425-040": "survivor"}}))
    check("different ABNs stop a merge until confirmed",
          not ok and "different ABNs" in err, err)
    ok, _o, err = as_in(pg, "f", SARAH, merge_sql("r0", A, [B], GOOD,
                        "'{\"" + B + "\": \"2026-09-01T00:00:00Z\"}'::jsonb"))
    check("an account changed since the preview is not merged",
          not ok and "changed after the preview" in err, err)

    # A failure part-way through rolls everything back.
    pg.psql("CREATE FUNCTION boom() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN IF NEW.order_number = 'B-2' THEN RAISE EXCEPTION 'disk "
            "full'; END IF; RETURN NEW; END $$; CREATE TRIGGER boom BEFORE "
            "UPDATE ON quotes FOR EACH ROW EXECUTE FUNCTION boom();"
            "DROP TRIGGER boom ON quotes; CREATE TRIGGER boom BEFORE UPDATE "
            "ON orders FOR EACH ROW EXECUTE FUNCTION boom();", "f")
    ok, _o, err = as_in(pg, "f", SARAH, merge_sql("r1", A, [B]))
    name = q(pg, f"SELECT is_active || ' ' || COALESCE(merged_into::text, "
                 f"'-') FROM customers WHERE id = '{B}';")
    check("a merge that fails part-way leaves nothing half done",
          not ok and "disk full" in err and snapshot(pg) == before
          and name == "true -", err + " / " + name)
    pg.psql("DROP TRIGGER boom ON orders;", "f")

    ok, mid, err = as_in(pg, "f", SARAH, merge_sql("r1", A, [B, E]))
    check("a manager merges two duplicates into the account that stays",
          ok and len(mid) == 36, err)
    after = snapshot(pg)
    rows = dict(r.split("=") for r in after.split(","))
    check("the duplicates' orders now belong to it, by id",
          all(rows[o] == f"CAS Tweed/{A}" for o in ("B-1", "B-2", "E-1")),
          after)
    check("its own orders are linked by id as well",
          all(rows[o].endswith(A) for o in ("A-1", "A-2", "A-3")), after)
    check("other companies and other branches are untouched",
          rows["C-1"] == "Total Comfort Air/-" and rows["D-1"] ==
          "CAS Bells/-", after)
    ids_same = q(pg, "SELECT count(*) FROM orders;") == "8"
    hdr = q(pg, "SELECT header ->> 'Customer Name' FROM orders "
                "WHERE order_number = 'B-1';")
    check("no order was recreated, and what was printed is unchanged",
          ids_same and hdr == "Complete Air Supply Tweed", hdr)
    qs = q(pg, "SELECT string_agg(quote_number || ':' || total || ':' || "
               "status || ':' || COALESCE(customer_id::text, '-'), ',' "
               "ORDER BY quote_number) FROM quotes;")
    check("quotes move with their numbers, totals and status as they were",
          qs == f"Q-1:1234.50:sent:{A},Q-2:100.25:accepted:{A},"
                f"Q-3:77.00:sent:{C}", qs)
    check("money is not double counted",
          q(pg, "SELECT sum(total) FROM quotes;") == totals_before)
    prices = q(pg, "SELECT string_agg(part_number || '=' || unit_price || "
                   "'/' || (customer_id = '" + A + "'), ',' ORDER BY "
                   "part_number, unit_price) FROM customer_prices "
                   f"WHERE customer_id IN ('{A}', '{B}');")
    check("the chosen agreed price stays and the other one moves over",
          prices == "FPFG425-040=10.00/true,PPFG450-060=5.00/true", prices)
    archived = q(pg, "SELECT string_agg(name || ':' || is_active || ':' || "
                     "(merged_into = '" + A + "'), ',' ORDER BY name) FROM "
                     f"customers WHERE id IN ('{B}', '{E}');")
    check("the duplicates are archived, not deleted, pointing at it",
          archived == "C.A.S. Tweed (old):false:true,"
                      "Complete Air Supply Tweed:false:true", archived)
    check("an old id leads to the account that stayed",
          q(pg, f"SELECT resolve_customer('{B}');") == A)
    aliases = q(pg, "SELECT string_agg(former_name, ',' ORDER BY "
                    "former_name) FROM customer_aliases;")
    check("and so do the old names",
          aliases == "C.A.S. Tweed (old),Complete Air Supply Tweed", aliases)
    po = q(pg, f"SELECT po_aliases FROM customers WHERE id = '{A}';")
    check("purchase-order wording learned on any of them still matches",
          "COMPLETE AIR TWEED" in po and "CAS TWEED HEADS" in po, po)
    sites = q(pg, "SELECT string_agg(name || '@' || customer_name, ',' "
                  "ORDER BY name) FROM sites;")
    check("sites move, and a different delivery address is kept as a site",
          sites == "Delivery address from Complete Air Supply Tweed@CAS "
                   "Tweed,Plant room 2@CAS Tweed", sites)
    check("returns and recurring jobs move",
          q(pg, "SELECT customer_name FROM returns;") == "CAS Tweed" and
          q(pg, "SELECT customer_name FROM recurring_jobs;") == "CAS Tweed")
    who = q(pg, f"SELECT merged_by_name || ':' || cardinality(merged_ids) "
                f"FROM customer_merges WHERE id = '{mid}';")
    check("who merged what, and when, is written down", who == "Sarah Boss:2",
          who)

    ok, again, err = as_in(pg, "f", SARAH, merge_sql("r1", A, [E, B]))
    check("a retry is answered with the same merge and moves nothing twice",
          ok and again == mid and snapshot(pg) == after and
          q(pg, "SELECT count(*) FROM customer_merges;") == "1", err)
    ok, _o, err = as_in(pg, "f", SARAH, merge_sql("r1", A, [C]))
    check("a request id cannot be reused for a different merge",
          not ok and "already used" in err, err)
    ok, _o, err = as_in(pg, "f", SARAH, merge_sql("r2", D, [B]))
    check("an account already merged cannot be merged again",
          not ok and "already been merged" in err, err)
    ok, _o, err = as_in(pg, "f", SARAH, merge_sql("r3", B, [A]))
    check("nor can anything be merged into one (no cycles)",
          not ok and "already been merged" in err, err)
    ok, _o, err = as_in(pg, "f", DAVE, "UPDATE customer_merges SET "
                        "merged_by_name = 'someone';")
    check("the record of a merge cannot be edited", not ok, err)

    print("\n── undoing it ──")
    ok, _o, err = as_in(pg, "f", DAVE, f"SELECT undo_customer_merge('{mid}');")
    check("somebody on the floor cannot undo a merge",
          not ok and "Only a manager" in err, err)
    ok, out, err = as_in(pg, "f", KAI, f"SELECT undo_customer_merge('{mid}');")
    check("a director can", ok and '"skipped": []' in out, out or err)
    check("every order is back exactly as it was", snapshot(pg) == before,
          snapshot(pg))
    prices = q(pg, "SELECT string_agg(part_number || '=' || unit_price || "
                   "'/' || (customer_id = '" + A + "'), ',' ORDER BY "
                   "part_number, unit_price) FROM customer_prices "
                   f"WHERE customer_id IN ('{A}', '{B}');")
    check("both agreed prices are back with their owners",
          prices == "FPFG425-040=9.50/false,FPFG425-040=10.00/true,"
                    "PPFG450-060=5.00/false", prices)
    back = q(pg, "SELECT string_agg(name || ':' || is_active, ',' ORDER BY "
                 f"name) FROM customers WHERE id IN ('{B}', '{E}');")
    check("the duplicates are live again",
          back == "C.A.S. Tweed (old):true,Complete Air Supply Tweed:true",
          back)
    check("the site made from the old address is gone, the real one is back",
          q(pg, "SELECT string_agg(name || '@' || customer_name, ',') "
                "FROM sites;") == "Plant room 2@Complete Air Supply Tweed")
    check("the aliases are gone",
          q(pg, "SELECT count(*) FROM customer_aliases;") == "0")
    ok, out, err = as_in(pg, "f", KAI, f"SELECT undo_customer_merge('{mid}');")
    check("undoing twice does nothing the second time",
          ok and '"already_undone": true' in out, out or err)

    # When the duplicate's price is the one kept, the survivor's is the one
    # removed - and undo has to move the duplicate's back off before the
    # survivor's can return to the same part number.
    ok, mid2, err = as_in(pg, "f", SARAH, merge_sql("r5", A, [B], {
        "set": {"name": "CAS - Tweed Heads"},
        "prices": {"FPFG425-040": B}}))
    won = q(pg, f"SELECT unit_price FROM customer_prices WHERE customer_id = "
                f"'{A}' AND part_number = 'FPFG425-040';")
    check("the duplicate's agreed price can be the one kept",
          ok and won == "9.50", won or err)
    ok, out, err = as_in(pg, "f", SARAH, f"SELECT undo_customer_merge('{mid2}');")
    prices = q(pg, "SELECT string_agg(part_number || '=' || unit_price || "
                   "'/' || (customer_id = '" + A + "'), ',' ORDER BY "
                   "part_number, unit_price) FROM customer_prices "
                   f"WHERE customer_id IN ('{A}', '{B}');")
    check("and undoing that puts both prices back with their owners",
          ok and '"skipped": []' in out and
          prices == "FPFG425-040=9.50/false,FPFG425-040=10.00/true,"
                    "PPFG450-060=5.00/false", (out or err) + " " + prices)

    # A name another live account also uses does not say whose a record is.
    q(pg, f"UPDATE customers SET short_name = 'Complete Air Supply Tweed' "
          f"WHERE id = '{D}';")
    ok, _o, err = as_in(pg, "f", SARAH, merge_sql("r9", A, [B]))
    rows = dict(r.split("=") for r in snapshot(pg).split(","))
    check("records under a name two live accounts share are not moved",
          ok and rows["B-1"] == "Complete Air Supply Tweed/-", rows["B-1"])

    print("\n── the name on their orders (step 36) ──")
    q(pg, "INSERT INTO orders (id, user_id, customer_name, order_number, "
          "header, items) VALUES (gen_random_uuid(), '" + DAVE + "', "
          "'CAS TWEED HEADS', 'A-9', '{\"Customer Name\": \"CAS TWEED "
          "HEADS\"}', '[]');")

    def names():
        return dict(r.split("=", 1) for r in q(pg,
            "SELECT string_agg(order_number || '=' || customer_name || '|' "
            "|| (header ->> 'Customer Name') || '|' || "
            "COALESCE(customer_id::text, '-'), ',' ORDER BY order_number) "
            "FROM orders;").split(","))
    before = names()
    ok, _o, err = as_in(pg, "f", DAVE,
                        f"SELECT sync_customer_order_names('{A}');")
    check("somebody on the floor cannot rename past orders",
          not ok and "Only a manager" in err, err)
    ok, _o, err = as_in(pg, "f", SARAH,
                        f"SELECT _sync_customer_order_names('{A}');")
    check("nor can anyone call the unchecked version", not ok, err)
    ok, n, err = as_in(pg, "f", SARAH,
                       f"SELECT sync_customer_order_names('{B}');")
    now = names()
    want = f"CAS Tweed|CAS Tweed|{A}"
    check("given an account merged away, it follows to the one that stayed",
          ok and int(n or 0) >= 3, n or err)
    check("the account's orders take its name - in the list and inside the "
          "order, which reprints read",
          all(now[o] == want for o in ("A-1", "A-2", "A-3")), str(now))
    check("an unlinked order under purchase-order wording it is known by "
          "is linked and renamed", now["A-9"] == want, now["A-9"])
    check("a name another live account uses, another branch and another "
          "company are left alone",
          now["B-1"] == before["B-1"] and now["B-2"] == before["B-2"] and
          now["D-1"] == before["D-1"] and
          now["C-1"] == before["C-1"] and now["E-1"] == before["E-1"],
          str(now))
    ok, n, err = as_in(pg, "f", SARAH,
                       f"SELECT sync_customer_order_names('{A}');")
    check("run again, there is nothing left to change", ok and n == "0",
          n or err)
    q(pg, f"UPDATE customers SET short_name = 'CAS - Tweed' WHERE id = '{A}';")
    ok, n, err = as_in(pg, "f", SARAH,
                       f"SELECT sync_customer_order_names('{A}');")
    check("after a rename, its orders follow",
          ok and names()["A-2"] == f"CAS - Tweed|CAS - Tweed|{A}",
          names()["A-2"])
    ok, _o, err = pg.psql((ROOT / "migrate_merge_names.sql").read_text(
        encoding="utf-8"), "f")
    check("step 36 runs again over merges already made, changing nothing "
          "already right", ok and names() == dict(names()), err)
    # An order an earlier merge moved to the account by id but whose name
    # was never changed - the case this step is for.
    q(pg, f"UPDATE orders SET customer_id = '{B}', customer_name = "
          f"'Complete Air Supply Tweed', header = header || "
          f"'{{\"Customer Name\": \"Complete Air Supply Tweed\"}}' "
          f"WHERE order_number = 'A-3';")
    ok, _o, err = pg.psql((ROOT / "migrate_merge_names.sql").read_text(
        encoding="utf-8"), "f")
    check("and puts right an old merge's order still showing the old name",
          ok and names()["A-3"] == f"CAS - Tweed|CAS - Tweed|{A}",
          names()["A-3"] + err)


XERO_MIGRATION = ROOT / "migrate_xero_link.sql"


def run_xero_checks(pg: Postgres) -> None:
    """Step 37, on the full schema the merge checks loaded."""
    print("\n── Xero, linked (step 37) ──")
    q(pg, "INSERT INTO catalog_lists (key, value) VALUES ('xero_tokens', "
          "'{\"refresh_token\": \"leaked\"}') ON CONFLICT (key) DO UPDATE "
          "SET value = EXCLUDED.value;")
    ok, _o, err = pg.psql(XERO_MIGRATION.read_text(encoding="utf-8"), "f")
    check("step 37 runs again cleanly", ok, err)
    check("the old Xero sign-in every account could read is gone",
          q(pg, "SELECT count(*) FROM catalog_lists "
                "WHERE key = 'xero_tokens';") == "0")

    # The merge checks' orders were all made moments ago: before the link.
    q(pg, "UPDATE orders SET created_at = now() - interval '3 hours';")
    q(pg, "SELECT xero_conn_put(jsonb_build_object('refresh_token', 'r1', "
          "'access_token', 'a1'));")
    check("a new link starts in the trial: nothing goes by itself",
          q(pg, "SELECT mode FROM xero_connection;") == "manual")
    trial = q(pg, "INSERT INTO orders (id, user_id, customer_name, "
                  "order_number, header, items) VALUES (gen_random_uuid(), "
                  f"'{DAVE}', 'Bells', 'T-1', '{{\"status\": \"Pending\"}}', "
                  "'[]') RETURNING id;").splitlines()[0]
    ok, out, err = as_in(pg, "f", DAVE,
                         "SELECT count(*) FROM xero_orders_to_draft(50);")
    check("in the trial no order is offered for a draft", ok and out == "0",
          out or err)
    q(pg, f"UPDATE orders SET header = header || '{{\"status\": "
          f"\"Complete\"}}' WHERE id = '{trial}';")
    check("and completing a job sends nothing - the button on the order does",
          q(pg, f"SELECT count(*) FROM xero_invoices "
                f"WHERE order_id = '{trial}';") == "0")
    # Sent from its button during the trial, then put back to Pending.
    q(pg, f"SELECT 1 FROM xero_claim('{trial}', 0);")
    q(pg, f"SELECT 1 FROM xero_invoice_put('{trial}', "
          "'{\"state\": \"draft\", \"invoice_id\": \"INV-T\"}');")
    q(pg, f"UPDATE orders SET header = header || '{{\"status\": "
          f"\"Pending\"}}' WHERE id = '{trial}';")
    q(pg, "SELECT xero_conn_put(jsonb_build_object('mode', 'automatic', "
          "'drafts_from', now() - interval '1 hour'));")
    q(pg, f"UPDATE orders SET created_at = now() - interval '2 hours' "
          f"WHERE id = '{trial}';")
    for who, label in ((DAVE, "somebody on the floor"),
                       (KAI, "a director")):
        ok, out, err = as_in(pg, "f", who,
                             "SELECT refresh_token FROM xero_connection;")
        check(f"{label} cannot read the Xero sign-in", not ok, out)
        ok, out, err = as_in(pg, "f", who, "SELECT xero_conn_get();")
        check(f"{label} cannot read it through the function's door either",
              not ok, out)
    ok, _o, err = as_in(pg, "f", SARAH, "UPDATE xero_connection SET "
                                        "refresh_token = 'mine';")
    check("nor can a manager change it", not ok, err)

    def new_order(number, created="now()", who=DAVE):
        return q(pg, "INSERT INTO orders (id, user_id, customer_name, "
                     "order_number, header, items, created_at) VALUES "
                     f"(gen_random_uuid(), '{who}', 'Bells', '{number}', "
                     f"'{{\"Order Number\": \"{number}\", \"status\": "
                     f"\"Pending\"}}', '[{{\"Quantity\": 2}}]', {created}) "
                     "RETURNING id;").splitlines()[0]

    old = new_order("X-OLD", "now() - interval '2 days'")
    fresh = new_order("X-1")
    ok, out, err = as_in(pg, "f", DAVE,
                         "SELECT string_agg(order_number, ',') FROM orders "
                         "WHERE id IN (SELECT order_id FROM "
                         "xero_orders_to_draft(50));")
    check("orders raised since Xero was linked are offered for a draft, "
          "older ones are not", ok and out == "X-1", out or err)
    ok, out, err = as_in(pg, "f", STRANGER,
                         "SELECT count(*) FROM xero_orders_to_draft(50);")
    check("an account that is not approved staff gets none",
          not ok and "Only staff" in err, out or err)
    ok, out, err = as_in(pg, "f", DAVE,
                         f"INSERT INTO xero_invoices (order_id) "
                         f"VALUES ('{fresh}');")
    check("staff cannot write the invoice rows themselves", not ok, out)

    first = q(pg, f"SELECT count(*) FROM xero_claim('{fresh}', 90);")
    second = q(pg, f"SELECT count(*) FROM xero_claim('{fresh}', 90);")
    check("an order is worked on by one request at a time",
          first == "1" and second == "0", f"{first}/{second}")
    ok, out, err = as_in(pg, "f", DAVE,
                         "SELECT count(*) FROM xero_orders_to_draft(50);")
    check("and is not offered again while it is held", ok and out == "0",
          out or err)

    md5 = q(pg, f"SELECT _xero_source_md5(o) FROM orders o "
                f"WHERE id = '{fresh}';")
    q(pg, f"SELECT 1 FROM xero_invoice_put('{fresh}', jsonb_build_object("
          f"'state', 'draft', 'invoice_id', 'INV-1', 'source_md5', '{md5}', "
          f"'claimed_until', null));")
    ok, out, err = as_in(pg, "f", DAVE,
                         "SELECT count(*) FROM xero_orders_to_draft(50);")
    check("an order whose draft is up to date is left alone",
          ok and out == "0", out or err)
    q(pg, f"UPDATE orders SET header = header || '{{\"Notes\": \"rush\"}}' "
          f"WHERE id = '{fresh}';")
    ok, out, err = as_in(pg, "f", DAVE,
                         "SELECT count(*) FROM xero_orders_to_draft(50);")
    check("a note does not send the draft round again", ok and out == "0",
          out or err)
    q(pg, f"UPDATE orders SET items = '[{{\"Quantity\": 3}}]' "
          f"WHERE id = '{fresh}';")
    ok, out, err = as_in(pg, "f", DAVE,
                         "SELECT count(*) FROM xero_orders_to_draft(50);")
    check("a changed line does", ok and out == "1", out or err)

    ok, out, err = as_in(pg, "f", DAVE,
                         f"SELECT merge_order_header('{fresh}', "
                         "'{\"status\": \"Complete\"}');")
    row = q(pg, f"SELECT complete_wanted || '/' || (completed_on = "
                f"(now() AT TIME ZONE 'Australia/Brisbane')::date) FROM "
                f"xero_invoices WHERE order_id = '{fresh}';")
    check("marking the job Complete - by anyone, from any screen - notes "
          "the day it was finished", ok and row == "true/true", row + err)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT xero_due_count();")
    check("and it is waiting to be approved and emailed",
          ok and out == "1", out or err)
    ok, out, err = as_in(pg, "f", DAVE,
                         "SELECT count(*) FROM xero_orders_to_draft(50);")
    check("a completed job's draft is not rewritten from the order",
          ok and out == "0", out or err)
    q(pg, f"UPDATE xero_invoices SET unpriced = 1 WHERE order_id = '{fresh}';")
    ok, out, err = as_in(pg, "f", DAVE,
                         "SELECT xero_due_count() || '/' || count(*) "
                         "FROM xero_orders_to_draft(50);")
    check("unless a line had no price: that holds it back, and fixing the "
          "order sends it again", ok and out == "0/1", out or err)
    q(pg, f"UPDATE xero_invoices SET unpriced = 0 WHERE order_id = '{fresh}';")

    q(pg, f"UPDATE orders SET header = header || "
          f"'{{\"status\": \"In Production\"}}' WHERE id = '{fresh}';")
    check("put back into production before it went, it waits again",
          q(pg, f"SELECT complete_wanted::text || '/' || "
                f"COALESCE(completed_on::text, '-') FROM xero_invoices "
                f"WHERE order_id = '{fresh}';") == "false/-")
    q(pg, f"UPDATE orders SET header = header || "
          f"'{{\"status\": \"Dispatched\"}}' WHERE id = '{fresh}';")
    check("going straight to Dispatched counts as finished",
          q(pg, f"SELECT complete_wanted FROM xero_invoices "
                f"WHERE order_id = '{fresh}';") == "t")
    q(pg, f"UPDATE orders SET header = header || '{{\"status\": "
          f"\"Complete\"}}' WHERE id = '{trial}';")
    check("once automatic, a trial order already in Xero is invoiced when "
          "its job is done",
          q(pg, f"SELECT complete_wanted FROM xero_invoices "
                f"WHERE order_id = '{trial}';") == "t")
    q(pg, f"UPDATE orders SET header = header || '{{\"status\": "
          f"\"Complete\"}}' WHERE id = '{old}';")
    check("an order from before the link is never invoiced by it",
          q(pg, f"SELECT count(*) FROM xero_invoices "
                f"WHERE order_id = '{old}';") == "0")

    q(pg, f"SELECT 1 FROM xero_invoice_put('{fresh}', "
          "'{\"state\": \"sent\"}');")
    q(pg, f"UPDATE orders SET header = header || "
          f"'{{\"status\": \"In Production\"}}' WHERE id = '{fresh}';")
    check("an invoice already sent is not pulled back by a status change",
          q(pg, f"SELECT complete_wanted FROM xero_invoices "
                f"WHERE order_id = '{fresh}';") == "t")

    gone = new_order("X-2")
    q(pg, f"SELECT 1 FROM xero_claim('{gone}', 0);")
    q(pg, f"SELECT 1 FROM xero_invoice_put('{gone}', "
          "'{\"state\": \"draft\", \"invoice_id\": \"INV-2\"}');")
    q(pg, f"DELETE FROM orders WHERE id = '{gone}';")
    check("deleting an order asks for its draft to come back out of Xero",
          q(pg, f"SELECT delete_wanted FROM xero_invoices "
                f"WHERE order_id = '{gone}';") == "t")

    q(pg, "ALTER TABLE xero_invoices ADD CONSTRAINT nope CHECK (false) "
          "NOT VALID;")
    late = new_order("X-3")
    ok, _o, err = pg.psql(f"UPDATE orders SET header = header || "
                          f"'{{\"status\": \"Complete\"}}' WHERE id = '{late}';",
                          "f")
    check("an order still saves when the Xero side cannot be written",
          ok and q(pg, f"SELECT header ->> 'status' FROM orders "
                       f"WHERE id = '{late}';") == "Complete", err)
    q(pg, "ALTER TABLE xero_invoices DROP CONSTRAINT nope;")

    ok, _o, err = pg.psql("SELECT xero_conn_put('{\"mode\": \"sometimes\"}');",
                          "f")
    check("the mode is only ever trial or automatic", not ok, err)

    a = q(pg, "SELECT COALESCE(xero_conn_begin_refresh(30), '-');")
    b = q(pg, "SELECT COALESCE(xero_conn_begin_refresh(30), '-');")
    check("the sign-in is renewed by one request at a time",
          a == "r1" and b == "-", f"{a}/{b}")
    stale = q(pg, "SELECT xero_conn_end_refresh('r0', "
                  "'{\"refresh_token\": \"x\"}');")
    good = q(pg, "SELECT xero_conn_end_refresh('r1', "
                 "'{\"refresh_token\": \"r2\", \"access_token\": \"a2\"}');")
    after = q(pg, "SELECT refresh_token || '/' || access_token || '/' || "
                  "(refreshing_until IS NULL) || '/' || (drafts_from IS NOT "
                  "NULL) FROM xero_connection;")
    check("a renewal that lost the race does not overwrite the winner's",
          stale == "f" and good == "t" and after == "r2/a2/true/true",
          f"{stale} {good} {after}")


def run_tier_checks(pg: Postgres) -> None:
    print("\n── price tiers (step 38) ──")
    ok, _o, err = pg.psql((ROOT / "migrate_price_tiers.sql").read_text(
        encoding="utf-8"), "f")
    check("step 38 runs again cleanly", ok, err)
    check("every customer starts on Tier 1",
          q(pg, "SELECT count(*) FROM customers WHERE price_tier <> 1;") == "0")
    ok, _o, err = pg.psql(f"UPDATE customers SET price_tier = 4 "
                          f"WHERE id = '{A}';", "f")
    check("there is no Tier 4", not ok, err)
    ok, _o, err = as_in(pg, "f", DAVE, f"UPDATE customers SET price_tier = 3 "
                                       f"WHERE id = '{A}' RETURNING id;")
    check("somebody on the floor cannot move a customer's tier",
          not ok and "Only a manager" in err, _o or err)
    ok, _o, err = as_in(pg, "f", DAVE, f"UPDATE customers SET notes = 'x' "
                                       f"WHERE id = '{A}' RETURNING id;")
    check("but can still edit the rest of the customer", ok and _o, err)
    ok, _o, err = as_in(pg, "f", SARAH, f"UPDATE customers SET price_tier = 3 "
                                        f"WHERE id = '{A}' RETURNING id;")
    check("a manager can", ok and _o, err)
    q(pg, "INSERT INTO price_list (part_number, unit_price, unit_price_3) "
          "VALUES ('TIER-1', 10, 8) ON CONFLICT (part_number) DO UPDATE SET "
          "unit_price_3 = 8;")
    check("a product carries a price for each tier, blank meaning Tier 1's",
          q(pg, "SELECT unit_price || '/' || COALESCE(unit_price_2::text, '-') "
                "|| '/' || unit_price_3 FROM price_list "
                "WHERE part_number = 'TIER-1';") == "10.0000/-/8.0000")


def run_customer_extra_checks(pg: Postgres) -> None:
    print("\n── Xero contact and delivery fee (step 39) ──")
    ok, _o, err = pg.psql((ROOT / "migrate_customer_xero_delivery.sql")
                          .read_text(encoding="utf-8"), "f")
    check("step 39 runs again cleanly", ok, err)
    ok, out, err = as_in(pg, "f", DAVE, f"UPDATE customers SET xero_contact_id "
                                        f"= 'C-1' WHERE id = '{A}' RETURNING id;")
    check("staff can link a customer to their Xero contact", ok and out, err)
    ok, out, err = as_in(pg, "f", DAVE, f"UPDATE customers SET delivery_fee = 25 "
                                        f"WHERE id = '{A}' RETURNING id;")
    check("somebody on the floor cannot set a delivery fee",
          not ok and "Only a manager" in err, out or err)
    ok, out, err = as_in(pg, "f", SARAH, f"UPDATE customers SET delivery_fee = 25 "
                                         f"WHERE id = '{A}' RETURNING id;")
    check("a manager can", ok and out, err)
    ok, _o, err = pg.psql(f"UPDATE customers SET delivery_fee = -1 "
                          f"WHERE id = '{A}';", "f")
    check("and it is never less than nothing", not ok, err)


def run_purchasing_checks(pg: Postgres) -> None:
    print("\n── buying through Xero (step 40) ──")
    ok, _o, err = pg.psql((ROOT / "migrate_purchasing.sql").read_text(
        encoding="utf-8"), "f")
    check("step 40 runs again cleanly", ok, err)
    ok, out, err = as_in(pg, "f", DAVE, "INSERT INTO suppliers (name) "
                                        "VALUES ('Vulcan') RETURNING id;")
    check("somebody on the floor cannot add a supplier", not ok, out)
    ok, sup, err = as_in(pg, "f", SARAH, "INSERT INTO suppliers (name, "
                                         "code_prefix) VALUES ('FD Greenwood', "
                                         "'FDG') RETURNING id;")
    check("a manager can", ok and sup, err)
    sup = (sup or "").splitlines()[0] if sup else ""

    q(pg, "DELETE FROM notifications;")
    lines = ('[{"item": "Channel", "detail": "45mm", "quantity": "20", '
             f'"supplier_id": "{sup}", "item_code": "FDG-C45"}}, '
             '{"item": "Rivets", "quantity": "2 boxes"}, '
             '{"item": "Tape", "detail": "50mm foil", "quantity": "6"}]')
    ok, out, err = as_in(pg, "f", DAVE,
                         f"SELECT count(*) FROM request_supplies('{lines}', "
                         "false, 'for the Batare job', 'ref-1');")
    check("several things asked for in one go", ok and out == "3", out or err)
    batch = q(pg, "SELECT count(DISTINCT batch_id) || '/' || "
                  "count(*) FILTER (WHERE supplier_id IS NOT NULL) || '/' || "
                  "min(requested_by_name) FROM supply_requests "
                  "WHERE client_ref LIKE 'ref-1-%';")
    check("as one batch, with its supplier, under who asked",
          batch == "1/1/Dave Floor", batch)
    told = q(pg, "SELECT count(*) || '/' || count(DISTINCT recipient) "
                 "FROM notifications WHERE kind = 'supply_request';")
    managers = q(pg, "SELECT count(*) FROM profiles WHERE approved AND "
                     "role IN ('Director','Admin','Manager');")
    check("each manager is told once, not once per item",
          told == f"{managers}/{managers}", f"{told} vs {managers}")
    ok, out, err = as_in(pg, "f", DAVE,
                         f"SELECT count(*) FROM request_supplies('{lines}', "
                         "false, '', 'ref-1');")
    check("sent again after a dropped connection, it is filed once",
          ok and out == "3" and q(pg, "SELECT count(*) FROM supply_requests "
                                      "WHERE client_ref LIKE 'ref-1-%';") == "3",
          out or err)
    ok, out, err = as_in(pg, "f", STRANGER,
                         f"SELECT count(*) FROM request_supplies('{lines}');")
    check("an account that is not staff cannot ask", not ok, out)

    item = q(pg, "INSERT INTO stock_items (name, stock_on_hand) VALUES "
                 "('45mm channel', 4) RETURNING id;").splitlines()[0]
    po = q(pg, "INSERT INTO purchase_orders (supplier, lines, po_number) "
               "VALUES ('FD Greenwood', '[{\"description\": \"45mm channel\", "
               f"\"quantity\": 20, \"stock_item_id\": \"{item}\"}}, "
               "{\"description\": \"Rivets\", \"quantity\": 2}]', "
               "'PO-0001') RETURNING id;").splitlines()[0]
    q(pg, f"UPDATE supply_requests SET purchase_order_id = '{po}', "
          f"status = 'ordered' WHERE client_ref LIKE 'ref-1-%';")
    ok, out, err = as_in(pg, "f", DAVE, f"SELECT status FROM receive_purchase("
                                        f"'{po}', '[{{\"line\": 0, \"qty\": 5}}]');")
    check("somebody on the floor cannot receive an order",
          not ok and "Only a manager" in err, out or err)
    ok, out, err = as_in(pg, "f", SARAH, f"SELECT status FROM receive_purchase("
                                         f"'{po}', '[{{\"line\": 0, \"qty\": 12}}]');")
    stock = q(pg, f"SELECT stock_on_hand::int FROM stock_items WHERE id = '{item}';")
    moved = q(pg, f"SELECT quantity_change::int || ' ' || transaction_type || ' ' "
                  f"|| notes FROM stock_transactions WHERE stock_item_id = '{item}';")
    check("part of an order in: part received, and into stock",
          ok and out == "part_received" and stock == "16" and
          moved == "12 receive PO PO-0001 from FD Greenwood",
          f"{out} {stock} {moved} {err}")
    ok, out, err = as_in(pg, "f", SARAH, f"SELECT status FROM receive_purchase("
                                         f"'{po}', '[{{\"line\": 0, \"qty\": 8}}, "
                                         f"{{\"line\": 1, \"qty\": 2}}]');")
    reqs = q(pg, "SELECT string_agg(DISTINCT status, ',') FROM supply_requests "
                 "WHERE client_ref LIKE 'ref-1-%';")
    check("the rest in: received, and the requests on it with it",
          ok and out == "received" and reqs == "received" and
          q(pg, f"SELECT stock_on_hand::int FROM stock_items "
                f"WHERE id = '{item}';") == "24", f"{out} {reqs} {err}")
    ok, out, err = as_in(pg, "f", SARAH, f"SELECT status FROM receive_purchase("
                                         f"'{po}', '[{{\"line\": 0, \"qty\": 1}}]');")
    check("and it cannot be received twice", not ok and "already" in err,
          out or err)


def run_stock_supplier_checks(pg: Postgres) -> None:
    print("\n── where each stock item comes from (step 42) ──")
    for _ in range(2):
        ok, _o, err = pg.psql((ROOT / "migrate_stock_suppliers.sql").read_text(
            encoding="utf-8"), "f")
        check("step 42 runs, and runs again cleanly", ok, err)
    item = q(pg, "INSERT INTO stock_items (name) VALUES ('C Channel 45') "
                 "RETURNING id;").splitlines()[0]
    fdg = q(pg, "SELECT id FROM suppliers WHERE name = 'FD Greenwood';")
    ad = q(pg, "INSERT INTO suppliers (name) VALUES ('Air Diffusion') "
               "RETURNING id;").splitlines()[0]
    ok, out, err = as_in(pg, "f", DAVE,
                         "INSERT INTO stock_item_suppliers (stock_item_id, "
                         f"supplier_id) VALUES ('{item}', '{fdg}') RETURNING id;")
    check("somebody on the floor cannot say where stock comes from", not ok, out)
    ok, out, err = as_in(pg, "f", SARAH,
                         "INSERT INTO stock_item_suppliers (stock_item_id, "
                         "supplier_id, supplier_code, preferred) VALUES "
                         f"('{item}', '{fdg}', 'FDG-C45-2440', true), "
                         f"('{item}', '{ad}', 'AD-C45', false) RETURNING id;")
    check("a manager can: channel from FD Greenwood and Air Diffusion",
          ok and len((out or "").splitlines()) == 2, out or err)
    ok, out, err = as_in(pg, "f", SARAH,
                         "UPDATE stock_item_suppliers SET preferred = true "
                         f"WHERE supplier_id = '{ad}';")
    check("only one of them can be preferred", not ok, out)
    ok, out, err = as_in(pg, "f", DAVE,
                         "SELECT count(*) FROM stock_item_suppliers "
                         f"WHERE stock_item_id = '{item}';")
    check("everybody on staff can see where it comes from",
          ok and out == "2", out or err)
    lines = ('[{"item": "C Channel 45", "quantity": "20", '
             f'"supplier_id": "{fdg}", "stock_item_id": "{item}"}}]')
    ok, out, err = as_in(pg, "f", DAVE,
                         f"SELECT stock_item_id FROM request_supplies('{lines}', "
                         "false, '', 'ref-42');")
    check("a request names the stock item asked for", ok and out == item,
          out or err)


def run_supply_bell_checks(pg: Postgres) -> None:
    print("\n── the bell only shows what still needs doing (step 43) ──")
    for _ in range(2):
        ok, _o, err = pg.psql((ROOT / "migrate_supply_bell.sql").read_text(
            encoding="utf-8"), "f")
        check("step 43 runs, and runs again cleanly", ok, err)

    def told(first):
        return q(pg, "SELECT count(*) FROM notifications "
                     f"WHERE kind = 'supply_request' AND ref_id = '{first}';")

    lines = ('[{"item": "Tape", "detail": "foil", "quantity": "3 rolls"}, '
             '{"item": "Rivets", "detail": "4mm", "quantity": "2 boxes"}]')
    ok, out, err = as_in(pg, "f", DAVE,
                         f"SELECT id FROM request_supplies('{lines}', false, "
                         "'', 'ref-43');")
    ids = (out or "").splitlines()
    check("two things asked for together tell each manager once",
          ok and len(ids) == 2 and told(ids[0]) not in ("", "0")
          and told(ids[1]) == "0", out or err)
    ok, _o, err = as_in(pg, "f", SARAH, "UPDATE supply_requests SET status = "
                                        f"'ordered' WHERE id = '{ids[0]}';")
    check("one of them ordered: still on the bell, the other is waiting",
          ok and told(ids[0]) not in ("", "0"), err or told(ids[0]))
    ok, _o, err = as_in(pg, "f", SARAH, "UPDATE supply_requests SET status = "
                                        f"'declined' WHERE id = '{ids[1]}';")
    check("the last one dealt with: off every manager's bell",
          ok and told(ids[0]) == "0", err or told(ids[0]))

    ok, out, err = as_in(pg, "f", DAVE, "SELECT id FROM request_supply("
                                        "'Media', 'G4', '1 roll', false, '', "
                                        "'ref-43b');")
    one = (out or "").strip()
    check("one thing asked for is on the bell", ok and told(one) not in ("", "0"),
          out or err)
    ok, _o, err = as_in(pg, "f", DAVE, "UPDATE supply_requests SET status = "
                                       f"'cancelled' WHERE id = '{one}';")
    check("and comes off when the person who asked cancels it",
          ok and told(one) == "0", err or told(one))

    # Dealt with before step 43 was run: cleared when it is.
    ok, out, err = as_in(pg, "f", DAVE, "SELECT id FROM request_supply("
                                        "'Channel', '45', '20', false, '', "
                                        "'ref-43c');")
    old = (out or "").strip()
    ok, out, err = as_in(pg, "f", DAVE, "SELECT id FROM request_supply("
                                        "'Channel', '50', '20', false, '', "
                                        "'ref-43d');")
    waiting = (out or "").strip()
    q(pg, "ALTER TABLE supply_requests DISABLE TRIGGER supply_requests_settle;"
          f"UPDATE supply_requests SET status = 'received' WHERE id = '{old}';"
          "ALTER TABLE supply_requests ENABLE TRIGGER supply_requests_settle;")
    ok, _o, err = pg.psql((ROOT / "migrate_supply_bell.sql").read_text(
        encoding="utf-8"), "f")
    check("running step 43 clears what was dealt with already, and only that",
          ok and told(old) == "0" and told(waiting) not in ("", "0"),
          err or f"{told(old)} {told(waiting)}")


def run_floor_checks(pg: Postgres) -> None:
    print("\n── the factory floor (step 44) ──")
    # The photos table comes with Storage, which this database has not got:
    # its shape, so the photo rule can be tried.
    q(pg, "CREATE TABLE IF NOT EXISTS order_files (id uuid PRIMARY KEY DEFAULT "
          "gen_random_uuid(), order_id uuid REFERENCES orders(id) ON DELETE "
          "CASCADE, kind text NOT NULL DEFAULT 'photo', path text NOT NULL, "
          "caption text NOT NULL DEFAULT '', signed_by text NOT NULL DEFAULT '', "
          "taken_by text NOT NULL DEFAULT '', created_at timestamptz NOT NULL "
          "DEFAULT now());")
    for _ in range(2):
        ok, _o, err = pg.psql((ROOT / "migrate_floor.sql").read_text(
            encoding="utf-8"), "f")
        check("step 44 runs, and runs again cleanly", ok, err)
    order = q(pg, "INSERT INTO orders (id, user_id, customer_name, order_number, "
                  "header, items) VALUES (gen_random_uuid(), '" + DAVE + "', "
                  "'Bells', 'F-44', '{\"status\": \"Pending\"}', "
                  "'[{\"line_id\": \"L1\", \"Filter Type\": \"V-Form\", "
                  "\"Quantity\": \"6\"}, {\"line_id\": \"L2\", "
                  "\"Filter Type\": \"Flat Panel\", \"Quantity\": 2}]') "
                  "RETURNING id;").splitlines()[0]

    ok, _o, err = as_in(pg, "f", SARAH, "UPDATE orders SET header = header || "
                        "'{\"status\": \"In Production\"}' "
                        f"WHERE id = '{order}';")
    stamp = q(pg, f"SELECT header ->> 'status_at' FROM orders WHERE id = '{order}';")
    check("a change of status is stamped with when", ok and stamp.endswith("Z")
          and stamp.startswith("20"), err or stamp)

    # The timer.
    ok, out, err = as_in(pg, "f", DAVE, "SELECT filter_type || '|' || quantity "
                         f"FROM start_job_timer('{order}', 'L1');")
    check("starting a timer on a line notes its type and how many",
          ok and out == "V-Form|6", out or err)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT filter_type FROM "
                         f"start_job_timer('{order}', 'L2');")
    running = q(pg, "SELECT count(*) FROM job_times WHERE stopped_at IS NULL;")
    check("starting another stops the first - one bench at a time",
          ok and running == "1", f"{out} {running} {err}")
    ok, out, err = as_in(pg, "f", DAVE, f"SELECT 1 FROM start_job_timer("
                         f"'{order}', 'nope');")
    check("a line that is not on the order is refused",
          not ok and "not on the order" in err, out or err)
    q(pg, "UPDATE job_times SET started_at = now() - interval '30 minutes' "
          "WHERE stopped_at IS NULL;")
    ok, out, err = as_in(pg, "f", DAVE, "SELECT round(minutes) FROM stop_job_timer();")
    check("stopping it works out the minutes", ok and out == "30", out or err)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT minutes_each FROM job_rates "
                         "WHERE filter_type = 'Flat Panel';")
    check("and how long each one takes", ok and out == "15.0", out or err)
    ok, _o, err = as_in(pg, "f", DAVE, "INSERT INTO job_times (filter_type, "
                        "minutes) VALUES ('V-Form', 1);")
    check("a time cannot be typed in, only timed", not ok, err)
    ok, _o, err = as_in(pg, "f", DAVE, "DELETE FROM job_times;")
    left = q(pg, "SELECT count(*) FROM job_times;")
    check("nor thrown away by somebody on the floor", left == "2", left)

    # Quality checks.
    ok, _o, err = as_in(pg, "f", DAVE, "INSERT INTO qc_checklists (filter_type, "
                        "checks) VALUES ('*', '[\"Size checked\"]');")
    check("somebody on the floor cannot write the checklists", not ok, err)
    ok, _o, err = as_in(pg, "f", SARAH, "INSERT INTO qc_checklists (filter_type, "
                        "checks) VALUES ('V-Form', '[\"Pleats even\"]');")
    check("a manager can", ok, err)
    ok, out, err = as_in(pg, "f", DAVE, f"SELECT 1 FROM set_order_line_qc('{order}', "
                         "'L1', '{\"passed\": true, \"by\": \"Dave\"}');")
    qc = q(pg, f"SELECT items -> 0 -> 'qc' ->> 'by' || '|' || "
               f"(items -> 1 ? 'qc')::text FROM orders WHERE id = '{order}';")
    check("the checks ticked are kept on that line, and only that line",
          ok and qc == "Dave|false", out or err or qc)

    # Faults.
    ok, _o, err = as_in(pg, "f", DAVE, "INSERT INTO returns (order_id, reason, "
                        "found, filter_type, made_by, line_id) VALUES "
                        f"('{order}', 'Wrong size', 'qc', 'V-Form', 'Dave', 'L1');")
    check("a fault found in QC is recorded against the line", ok, err)
    ok, _o, err = as_in(pg, "f", DAVE, "INSERT INTO returns (reason, found) "
                        "VALUES ('x', 'somewhere');")
    check("and where it was found is one of the three", not ok, err)

    # The finished photo, once it is required.
    q(pg, "INSERT INTO feature_switches (key, enabled) VALUES "
          "('finished_photo', true) ON CONFLICT (key) DO UPDATE SET enabled = true;")
    ok, _o, err = as_in(pg, "f", SARAH, "UPDATE orders SET header = header || "
                        "'{\"status\": \"Complete\"}' "
                        f"WHERE id = '{order}';")
    check("with the switch on, no photo means it cannot be Complete",
          not ok and "photo of the finished job" in err, err)
    q(pg, "INSERT INTO order_files (order_id, kind, path, bucket) VALUES "
          f"('{order}', 'finished', '{order}/a.jpg', 'job-photos');")
    ok, _o, err = as_in(pg, "f", SARAH, "UPDATE orders SET header = header || "
                        "'{\"status\": \"Complete\"}' "
                        f"WHERE id = '{order}';")
    check("with one it can", ok, err)
    q(pg, "UPDATE feature_switches SET enabled = false WHERE key = 'finished_photo';")


def run_planning_checks(pg: Postgres) -> None:
    print("\n── the roster and leave (step 45) ──")
    for _ in range(2):
        ok, _o, err = pg.psql((ROOT / "migrate_planning.sql").read_text(
            encoding="utf-8"), "f")
        check("step 45 runs, and runs again cleanly", ok, err)
    ok, _o, err = as_in(pg, "f", DAVE, "INSERT INTO staff_roster (person) "
                        "VALUES ('Dave');")
    check("somebody on the floor cannot change the roster", not ok, err)
    ok, _o, err = as_in(pg, "f", SARAH, "INSERT INTO staff_roster (person, "
                        "days, hours) VALUES ('Dave', '{1,2,3,4,5}', 7.6);")
    check("a manager can", ok, err)
    ok, _o, err = as_in(pg, "f", SARAH, "INSERT INTO staff_roster (person, "
                        "days) VALUES ('Nobody', '{0,8}');")
    check("days are Monday 1 to Sunday 7", not ok, err)
    ok, _o, err = as_in(pg, "f", SARAH, "INSERT INTO staff_leave (person, "
                        "first_day, last_day) VALUES ('Dave', '2026-10-20', "
                        "'2026-10-19');")
    check("leave cannot end before it starts", not ok, err)
    ok, _o, err = as_in(pg, "f", SARAH, "INSERT INTO staff_leave (person, "
                        "first_day, last_day, kind) VALUES ('Dave', "
                        "'2026-10-19', '2026-10-23', 'annual');")
    check("a week of leave is kept", ok, err)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT count(*) FROM staff_leave;")
    check("and everybody can see who is away", ok and out == "1", out or err)
    got = q(pg, "SELECT value FROM workshop_settings "
                "WHERE key = 'minutes_per_filter';")
    check("the minutes a filter takes until it is timed is there", got == "15", got)


def run_sales_checks(pg: Postgres) -> None:
    print("\n── winning the work (step 46) ──")
    for _ in range(2):
        ok, _o, err = pg.psql((ROOT / "migrate_sales.sql").read_text(
            encoding="utf-8"), "f")
        check("step 46 runs, and runs again cleanly", ok, err)
    q(pg, "INSERT INTO price_list (part_number, unit_price, unit_price_2) "
          "VALUES ('TAF-G4-595', 20, 18) ON CONFLICT (part_number) DO UPDATE "
          "SET unit_price = 20, unit_price_2 = 18, unit_price_3 = NULL;")
    q(pg, "INSERT INTO price_rates (filter_type, media_type, rate_per_sqm) "
          "VALUES ('V-Form', 'G4', 30) ON CONFLICT (filter_type, media_type) "
          "DO UPDATE SET rate_per_sqm = 30;")
    ok, _o, err = as_in(pg, "f", DAVE, "INSERT INTO price_changes (percent) "
                        "VALUES (10);")
    check("somebody on the floor cannot put through a price change", not ok, err)
    ok, out, err = as_in(pg, "f", SARAH, "INSERT INTO price_changes (scope, "
                         "match_text, tiers, percent) VALUES ('list', 'G4', "
                         "'{1,2,3}', 10) RETURNING id;")
    change = (out or "").splitlines()[0] if ok and out else ""
    check("a manager can", ok and change, out or err)
    ok, out, err = as_in(pg, "f", DAVE, f"SELECT apply_price_change('{change}');")
    check("and only a manager can apply it", not ok, out or err)
    ok, out, err = as_in(pg, "f", SARAH, f"SELECT apply_price_change('{change}');")
    prices = q(pg, "SELECT unit_price || '|' || unit_price_2 || '|' || "
                   "COALESCE(unit_price_3::text, '-') FROM price_list "
                   "WHERE part_number = 'TAF-G4-595';")
    check("applied: 10% on each tier that has a price, to the cent",
          ok and out == "1" and prices == "22.0000|19.8000|-", f"{out} {prices} {err}")
    ok, out, err = as_in(pg, "f", SARAH, f"SELECT apply_price_change('{change}');")
    again = q(pg, "SELECT unit_price FROM price_list WHERE part_number = 'TAF-G4-595';")
    check("and never twice", ok and out == "0" and again == "22.0000", f"{out} {again}")
    rate = q(pg, "SELECT rate_per_sqm FROM price_rates WHERE filter_type = 'V-Form';")
    check("a change to part numbers leaves the square-metre rates alone",
          rate == "30.0000", rate)
    q(pg, "INSERT INTO price_changes (scope, percent, starts_on) VALUES "
          "('rates', 5, current_date), ('rates', 5, current_date + 30);")
    ok, out, err = as_in(pg, "f", SARAH, "SELECT apply_due_price_changes();")
    rate = q(pg, "SELECT rate_per_sqm FROM price_rates WHERE filter_type = 'V-Form';")
    left = q(pg, "SELECT count(*) FROM price_changes WHERE applied_at IS NULL;")
    check("what is due by today is applied; what starts next month waits",
          ok and rate == "31.5000" and left == "1", f"{out} {rate} {left} {err}")
    ok, out, err = as_in(pg, "f", DAVE, "SELECT apply_due_price_changes();")
    check("from anybody else's PC it does nothing", ok and out == "0", out or err)

    quote = q(pg, "INSERT INTO quotes (quote_number, status) VALUES "
                  "('Q-46', 'sent') RETURNING id;").splitlines()[0]
    ok, out, err = as_in(pg, "f", DAVE, f"SELECT quote_chased('{quote}');")
    ok2, out2, err2 = as_in(pg, "f", DAVE, f"SELECT quote_chased('{quote}');")
    check("chasing a quote counts each chase", ok and ok2 and out2 == "2",
          f"{out} {out2} {err or err2}")
    ok, _o, err = as_in(pg, "f", SARAH, "UPDATE customers SET service_weeks = 0 "
                        "WHERE true;")
    check("a filter change every 0 weeks is refused", not ok, err)


def run_stock_insight_checks(pg: Postgres) -> None:
    print("\n── stock you can trust (step 47) ──")
    for _ in range(2):
        ok, _o, err = pg.psql((ROOT / "migrate_stock_insight.sql").read_text(
            encoding="utf-8"), "f")
        check("step 47 runs, and runs again cleanly", ok, err)
    item = q(pg, "INSERT INTO stock_items (name, stock_on_hand) VALUES "
                 "('Rivets 4mm', 12) RETURNING id;").splitlines()[0]
    take = q(pg, "INSERT INTO stocktakes (name) VALUES ('Back rack') "
                 "RETURNING id;").splitlines()[0]
    for _ in range(2):
        ok, out, err = as_in(pg, "f", DAVE, f"SELECT count_stock('{take}', "
                             f"'{item}', 9, 'Dave');")
    got = q(pg, "SELECT count(*) || '|' || max(counted) || '|' || max(was) FROM "
                f"stocktake_counts WHERE stocktake_id = '{take}';")
    check("a count from the phone, sent twice, is one count with what the "
          "system said", ok and got == "1|9|12.000", got or err)
    ok, out, err = as_in(pg, "f", DAVE, f"SELECT count_stock('{take}', "
                         f"'{item}', -1, 'Dave');")
    check("a count below nothing writes nothing", ok and out == "", out or err)
    q(pg, f"UPDATE stocktakes SET finished_at = now() WHERE id = '{take}';")
    ok, out, err = as_in(pg, "f", DAVE, f"SELECT count_stock('{take}', "
                         f"'{item}', 3, 'Dave');")
    got = q(pg, f"SELECT max(counted) FROM stocktake_counts WHERE stocktake_id = '{take}';")
    check("nor anything to a stocktake that is finished", got == "9", got)

    rows = ('[{"item_id": "' + item + '", "reserved": 4, "orders": 2}, '
            '{"item_id": "00000000-0000-0000-0000-0000000000ff", "reserved": 1}]')
    ok, out, err = as_in(pg, "f", DAVE, f"SELECT set_stock_reserved('{rows}');")
    got = q(pg, "SELECT string_agg(reserved || '/' || orders, ',') FROM stock_reserved;")
    check("what open orders speak for is written all at once, for real items",
          ok and out == "1" and got == "4/2", (out or err) + " " + got)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT set_stock_reserved('[]');")
    got = q(pg, "SELECT count(*) FROM stock_reserved;")
    check("and replaced each time", ok and got == "0", got or err)

    sup = q(pg, "SELECT id FROM suppliers WHERE name = 'FD Greenwood';")
    lines = ('[{"item_code": "FDG-C45", "unit_price": 18.5, "quantity": 20, '
             f'"stock_item_id": "{item}"}}, {{"item_code": "X", "unit_price": "tbc"}}]')
    q(pg, "INSERT INTO purchase_orders (supplier, supplier_id, status, lines, "
          "created_at, sent_at, received_at) VALUES ('FD Greenwood', "
          f"'{sup}', 'received', '{lines}', now() - interval '10 days', "
          "now() - interval '9 days', now() - interval '2 days');")
    ok, out, err = as_in(pg, "f", DAVE, "SELECT item_code || '|' || unit_price "
                         "|| '|' || quantity FROM supplier_prices "
                         "WHERE supplier = 'FD Greenwood';")
    check("what was paid is listed by item, and a price that is not one is "
          "left out", ok and out == "FDG-C45|18.5|20", out or err)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT median_days FROM "
                         f"supplier_lead_times WHERE supplier_id = '{sup}';")
    check("and how long the supplier took, sent to received",
          ok and out == "7.0", out or err)


def run_delivery_money_checks(pg: Postgres) -> None:
    print("\n── out the door, and what it made (step 48) ──")
    for _ in range(2):
        ok, _o, err = pg.psql((ROOT / "migrate_delivery_money.sql").read_text(
            encoding="utf-8"), "f")
        check("step 48 runs, and runs again cleanly", ok, err)
    lines = ('[{"Unit Price": 27.5, "Quantity": "4"}, '
             '{"Unit Price": "", "Quantity": 2}, '
             '{"item_kind": "bag", "Unit Price": 3, "quantity": 10}]')
    head = '{"Delivery Fee": "$25", "status": "Complete"}'
    a = q(pg, "INSERT INTO orders (user_id, customer_name, order_number, items, "
              f"header) VALUES ('{DAVE}', 'Bells Creek', 'PO-48A', '{lines}', "
              f"'{head}') RETURNING id;").splitlines()[0]
    b = q(pg, "INSERT INTO orders (user_id, customer_name, order_number, items, "
              f"header) VALUES ('{DAVE}', 'Tweed', 'PO-48B', 'null', '{{}}') "
              "RETURNING id;").splitlines()[0]
    ok, out, err = as_in(pg, "f", DAVE, "SELECT value || '|' || unpriced || '|' "
                         f"|| delivery_fee || '|' || status FROM order_values "
                         f"WHERE id = '{a}';")
    check("an order is worth its priced lines and its delivery fee, with the "
          "lines that have no price counted", ok and out == "165.00|1|25.00|Complete",
          out or err)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT value || '|' || status FROM "
                         f"order_values WHERE id = '{b}';")
    check("an order with no lines is worth nothing, not an error",
          ok and out == "0.00|Pending", out or err)

    ok, _o, err = as_in(pg, "f", DAVE, "INSERT INTO delivery_runs (run_date, stops) "
                        f"VALUES ('2026-10-20', ARRAY['{b}', '{a}']::uuid[]);")
    ok2, _o, err2 = as_in(pg, "f", DAVE, "UPDATE delivery_runs SET stops = "
                          f"ARRAY['{a}', '{b}']::uuid[] WHERE run_date = '2026-10-20';")
    got = q(pg, "SELECT stops[1] FROM delivery_runs WHERE run_date = '2026-10-20';")
    check("the driver can set and change the order of the run",
          ok and ok2 and got == a, err or err2 or got)

    ok, _o, err = as_in(pg, "f", DAVE, "INSERT INTO sales_targets (month, target) "
                        "VALUES ('2026-10-01', 60000);")
    check("somebody on the floor cannot set a sales target", not ok)
    ok, _o, err = as_in(pg, "f", SARAH, "INSERT INTO sales_targets (month, target) "
                        "VALUES ('2026-10-01', 60000);")
    check("a manager can", ok, err)
    ok, _o, err = as_in(pg, "f", SARAH, "INSERT INTO sales_targets (month, target) "
                        "VALUES ('2026-11-15', 60000);")
    check("a target is for a whole month", not ok)

    ok, _o, err = as_in(pg, "f", SARAH, "INSERT INTO delivery_proofs (order_id, "
                        f"emailed_to) VALUES ('{a}', 'someone@example.com');")
    check("nobody can say a proof of delivery was emailed - only the function "
          "that sent it", not ok)
    ok, _o, err = as_in(pg, "f", SARAH, "INSERT INTO owner_reports (month) "
                        "VALUES ('2026-09-01');")
    check("nor that an owner's report went", not ok)
    q(pg, "INSERT INTO owner_reports (month, sent_to) VALUES ('2026-09-01', "
          "'{kai@taf.example}');")
    ok, out, err = as_in(pg, "f", DAVE, "SELECT count(*) FROM owner_reports;")
    ok2, out2, err2 = as_in(pg, "f", SARAH, "SELECT count(*) FROM owner_reports;")
    check("managers can see which reports went; the floor cannot",
          ok and out == "0" and ok2 and out2 == "1", f"{out} {out2} {err}{err2}")


def run_staff_board_checks(pg: Postgres) -> None:
    print("\n── how-tos, the noticeboard and groups (step 49) ──")
    for _ in range(2):
        ok, _o, err = pg.psql((ROOT / "migrate_staff_board.sql").read_text(
            encoding="utf-8"), "f")
        check("step 49 runs, and runs again cleanly", ok, err)
    got = q(pg, "SELECT count(*) FROM chat_channels WHERE kind = 'board';")
    check("there is one noticeboard, however many times it runs", got == "1", got)

    # ── How-tos ──
    ok, _o, err = as_in(pg, "f", DAVE, "INSERT INTO sops (title) VALUES ('Mine');")
    check("somebody on the floor cannot write a how-to", not ok)
    ok, out, err = as_in(pg, "f", SARAH, "INSERT INTO sops (title, filter_type, body) "
                         "VALUES ('Making a V-form', 'V-form', 'Step 1') RETURNING id;")
    sop = out.splitlines()[0] if ok and out else ""
    check("a manager can", ok and sop, err)
    ok, _o, err = as_in(pg, "f", SARAH, "INSERT INTO sops (title, video_url) "
                        "VALUES ('Bad', 'javascript:alert(1)');")
    check("a video link has to be a web address", not ok)
    ok, out, err = as_in(pg, "f", DAVE, f"SELECT read_sop('{sop}');")
    check("reading it signs off the version that is there", ok and out == "1", out or err)
    q(pg, f"UPDATE sops SET category = 'Floor' WHERE id = '{sop}';")
    got = q(pg, f"SELECT version FROM sops WHERE id = '{sop}';")
    check("a new category is not a new version", got == "1", got)
    ok, _o, err = as_in(pg, "f", SARAH, f"UPDATE sops SET body = 'Step 1, then 2' "
                        f"WHERE id = '{sop}';")
    got = q(pg, f"SELECT version FROM sops WHERE id = '{sop}';")
    check("changing what it says is", ok and got == "2", got or err)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT count(*) FROM sop_reads;")
    ok2, out2, err2 = as_in(pg, "f", SARAH, "SELECT person || ' v' || version FROM sop_reads;")
    check("people see their own sign-offs, managers see everybody's",
          ok and out == "1" and ok2 and out2 == "Dave Floor v1", f"{out} {out2} {err}{err2}")
    ok, _o, err = as_in(pg, "f", DAVE, "INSERT INTO sop_reads (sop_id, user_id, version) "
                        f"VALUES ('{sop}', '{DAVE}', 2);")
    check("nobody can sign off a version by hand", not ok)
    ok, _o, err = as_in(pg, "f", STRANGER, f"SELECT read_sop('{sop}');")
    check("an account nobody approved cannot sign anything off", not ok)

    # ── The noticeboard ──
    board = q(pg, "SELECT id FROM chat_channels WHERE kind = 'board';")
    ok, _o, err = as_in(pg, "f", DAVE, "INSERT INTO chat_messages (channel_id, body) "
                        f"VALUES ('{board}', 'hello all');")
    check("out of the box, somebody on the floor cannot post on the noticeboard", not ok)
    ok, out, err = as_in(pg, "f", SARAH, "INSERT INTO chat_messages (channel_id, body, "
                         f"user_id) VALUES ('{board}', 'Toolbox talk Friday', '{SARAH}') "
                         "RETURNING id, author;")
    msg, author = (out.split("|") + ["", ""])[:2] if ok else ("", "")
    check("a manager can, under their own name", ok and author == "Sarah Boss", out or err)
    ok, _o, err = as_in(pg, "f", SARAH, "INSERT INTO chat_messages (channel_id, body, "
                        f"user_id) VALUES ('{board}', 'as Kai', '{KAI}');")
    check("nobody posts as somebody else", not ok)
    ok, _o, err = as_in(pg, "f", SARAH, "INSERT INTO chat_messages (channel_id, body, "
                        f"pinned) VALUES ('{board}', 'pinned on the way in', true);")
    check("nor sneaks a pin in with the message", not ok)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT body FROM chat_messages "
                         f"WHERE channel_id = '{board}';")
    check("everybody on staff reads the noticeboard", ok and out == "Toolbox talk Friday",
          out or err)
    ok, out, err = as_in(pg, "f", STRANGER, "SELECT count(*) FROM chat_messages;")
    check("an account nobody approved reads nothing", ok and out == "0", out or err)
    ok, _o, err = as_in(pg, "f", SARAH, f"SELECT pin_message('{msg}', true);")
    check("out of the box a manager cannot pin", not ok)
    ok, _o, err = as_in(pg, "f", KAI, f"SELECT pin_message('{msg}', true);")
    got = q(pg, f"SELECT pinned || '|' || pinned_by FROM chat_messages WHERE id = '{msg}';")
    check("a director can, and is named for it", ok and got == "true|Kai Brown", got or err)
    ok, _o, err = as_in(pg, "f", SARAH, "UPDATE chat_messages SET pinned = false;")
    got = q(pg, f"SELECT pinned FROM chat_messages WHERE id = '{msg}';")
    check("a message cannot be changed directly", got == "t", got)

    ok, _o, err = as_in(pg, "f", SARAH, "UPDATE chat_rules SET min_role = 'Employee' "
                        "WHERE action = 'post_board';")
    got = q(pg, "SELECT min_role FROM chat_rules WHERE action = 'post_board';")
    check("a manager cannot change who may do what", got == "Manager", got)
    ok, _o, err = as_in(pg, "f", AMY, "UPDATE chat_rules SET min_role = 'Employee' "
                        "WHERE action = 'post_board';")
    ok2, _o, err2 = as_in(pg, "f", DAVE, "INSERT INTO chat_messages (channel_id, body, "
                          f"user_id) VALUES ('{board}', 'thanks!', '{DAVE}');")
    check("an admin can - and then the floor can post", ok and ok2, err or err2)
    ok, _o, err = as_in(pg, "f", AMY, "UPDATE chat_rules SET min_role = 'Director' "
                        "WHERE action = 'pin';")
    check("a rule is one of the three roles", not ok)

    # ── Groups ──
    ok, _o, err = as_in(pg, "f", DAVE, "SELECT make_group('Floor crew', "
                        f"ARRAY['{SARAH}']::uuid[]);")
    check("out of the box, somebody on the floor cannot start a group", not ok)
    ok, out, err = as_in(pg, "f", SARAH, "SELECT make_group('Night shift', "
                         f"ARRAY['{DAVE}', '{STRANGER}']::uuid[]);")
    grp = out if ok else ""
    got = q(pg, f"SELECT count(*) FROM chat_members WHERE channel_id = '{grp}';")
    check("a manager can, with the people they name who are approved", ok and got == "2",
          got or err)
    ok, _o, err = as_in(pg, "f", DAVE, "INSERT INTO chat_messages (channel_id, body, "
                        f"user_id) VALUES ('{grp}', 'running late', '{DAVE}');")
    check("its members can post in it", ok, err)
    ok, out, err = as_in(pg, "f", AMY, "SELECT count(*) FROM chat_messages "
                         f"WHERE channel_id = '{grp}';")
    check("people not in it cannot read it, admins included", ok and out == "0", out or err)
    ok, _o, err = as_in(pg, "f", AMY, "INSERT INTO chat_messages (channel_id, body, "
                        f"user_id) VALUES ('{grp}', 'hi', '{AMY}');")
    check("or post in it", not ok)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT name || '|' || unread FROM my_chats() "
                         "ORDER BY kind;")
    check("my chats lists the noticeboard and my groups, with what I have not read",
          ok and out.splitlines() == ["Noticeboard|1", "Night shift|0"], out or err)
    ok, _o, err = as_in(pg, "f", DAVE, f"SELECT mark_chat_read('{board}');")
    ok2, out, err2 = as_in(pg, "f", DAVE, "SELECT unread FROM my_chats() "
                           "WHERE kind = 'board';")
    check("reading it clears the count", ok and ok2 and out == "0", out or err or err2)
    ok, _o, err = as_in(pg, "f", DAVE, "SELECT set_group_members("
                        f"'{grp}', ARRAY['{DAVE}', '{AMY}']::uuid[]);")
    check("somebody who did not start a group cannot change who is in it", not ok)
    ok, out, err = as_in(pg, "f", SARAH, "SELECT set_group_members("
                         f"'{grp}', ARRAY['{AMY}']::uuid[]);")
    got = q(pg, f"SELECT count(*) FROM chat_members WHERE channel_id = '{grp}' "
                f"AND user_id = '{DAVE}';")
    check("whoever started it can, and keeps their own place", ok and out == "2" and got == "0",
          f"{out} {got} {err}")

    # ── Taking down ──
    dave_msg = q(pg, f"SELECT id FROM chat_messages WHERE user_id = '{DAVE}' "
                     f"AND channel_id = '{board}';")
    ok, _o, err = as_in(pg, "f", DAVE, f"SELECT remove_message('{msg}');")
    check("you cannot take down somebody else's message", not ok)
    ok, _o, err = as_in(pg, "f", DAVE, f"SELECT remove_message('{dave_msg}');")
    got = q(pg, f"SELECT body = '' AND removed_at IS NOT NULL FROM chat_messages "
                f"WHERE id = '{dave_msg}';")
    check("but you can take down your own - what it said is gone", ok and got == "t", got or err)
    ok, _o, err = as_in(pg, "f", AMY, f"SELECT remove_message('{msg}');")
    got = q(pg, f"SELECT pinned FROM chat_messages WHERE id = '{msg}';")
    check("an admin can take down anybody's, and it is no longer pinned",
          ok and got == "f", got or err)


def run_direct_message_checks(pg: Postgres) -> None:
    print("\n── private messages (step 50) ──")
    for _ in range(2):
        ok, _o, err = pg.psql((ROOT / "migrate_direct_messages.sql").read_text(
            encoding="utf-8"), "f")
        check("step 50 runs, and runs again cleanly", ok, err)
    ok, out, err = as_in(pg, "f", DAVE, f"SELECT open_direct('{KAI}');")
    dm = out if ok else ""
    check("anybody on staff can message anybody else on staff", ok and dm, err)
    ok, out, err = as_in(pg, "f", KAI, f"SELECT open_direct('{DAVE}');")
    check("there is one conversation between two people, whoever starts it",
          ok and out == dm, f"{out} {dm} {err}")
    ok, _o, err = as_in(pg, "f", DAVE, f"SELECT open_direct('{DAVE}');")
    check("nobody messages themselves", not ok)
    ok, _o, err = as_in(pg, "f", DAVE, f"SELECT open_direct('{STRANGER}');")
    check("nor an account nobody approved", not ok)
    ok, _o, err = as_in(pg, "f", STRANGER, f"SELECT open_direct('{DAVE}');")
    check("and an account nobody approved cannot message anybody", not ok)
    ok, _o, err = as_in(pg, "f", DAVE, "INSERT INTO chat_messages (channel_id, body, "
                        f"user_id) VALUES ('{dm}', 'can I leave at 3?', '{DAVE}');")
    check("either of them can write in it", ok, err)
    ok, out, err = as_in(pg, "f", KAI, "SELECT name || '|' || unread FROM my_chats() "
                         "WHERE kind = 'direct';")
    check("it is named after the other person, with what is new",
          ok and out == "Dave Floor|1", out or err)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT name FROM my_chats() WHERE kind = 'direct';")
    check("for both of them", ok and out == "Kai Brown", out or err)
    for who in (AMY, SARAH):
        ok, out, err = as_in(pg, "f", who, "SELECT count(*) FROM chat_messages "
                             f"WHERE channel_id = '{dm}';")
        check("nobody else can read it, an admin included" if who == AMY
              else "nor a manager", ok and out == "0", out or err)
    ok, _o, err = as_in(pg, "f", AMY, "INSERT INTO chat_messages (channel_id, body, "
                        f"user_id) VALUES ('{dm}', 'hi', '{AMY}');")
    check("or write in it", not ok)
    ok, _o, err = as_in(pg, "f", KAI, f"SELECT set_group_members('{dm}', "
                        f"ARRAY['{AMY}']::uuid[]);")
    check("and nobody can be added to it", not ok)
    ok, out, err = as_in(pg, "f", DAVE, "SELECT kind FROM my_chats() LIMIT 1;")
    check("the noticeboard still comes first", ok and out == "board", out or err)


def _skip(why: str) -> int:
    """Skipping is fine on a laptop. In CI it is not: a workflow that goes
    green having checked nothing is worse than no workflow, because it is
    believed. REQUIRE_POSTGRES turns a skip into a failure there."""
    if os.environ.get("REQUIRE_POSTGRES"):
        print(f"FAIL: {why} - and this run requires it")
        return 1
    print(f"SKIP: {why}")
    return 0


def main() -> int:
    for name in ("initdb", "pg_ctl", "psql"):
        if not _bin(name):
            return _skip(f"{name} is not installed")
    pg = Postgres()
    if not pg.start():
        return _skip("could not start a throwaway Postgres")
    try:
        run_checks(pg)
        run_merge_checks(pg)
        run_xero_checks(pg)
        run_tier_checks(pg)
        run_customer_extra_checks(pg)
        run_purchasing_checks(pg)
        run_stock_supplier_checks(pg)
        run_supply_bell_checks(pg)
        run_floor_checks(pg)
        run_planning_checks(pg)
        run_sales_checks(pg)
        run_stock_insight_checks(pg)
        run_delivery_money_checks(pg)
        run_staff_board_checks(pg)
        run_direct_message_checks(pg)
    finally:
        pg.stop()
    print(f"\n{len(FAILURES)} FAILED" if FAILURES
          else "\nThe database holds its own rules.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
