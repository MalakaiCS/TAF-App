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
    finally:
        pg.stop()
    print(f"\n{len(FAILURES)} FAILED" if FAILURES
          else "\nThe database holds its own rules.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
